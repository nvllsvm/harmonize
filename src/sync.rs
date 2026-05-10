use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use filetime::FileTime;
use ignore::gitignore::{Gitignore, GitignoreBuilder};
use tokio::sync::Semaphore;
use tokio::task::JoinSet;

use crate::config::{Config, Mapping};
use crate::converter;

fn lowercase_ext(path: &Path) -> String {
    path.extension()
        .map(|e| format!(".{}", e.to_string_lossy().to_lowercase()))
        .unwrap_or_default()
}

pub fn build_target_path(
    source_path: &Path,
    source_base: &Path,
    target_base: &Path,
    mappings: &HashMap<String, Mapping>,
) -> PathBuf {
    let rel = source_path
        .strip_prefix(source_base)
        .expect("source_path must be under source_base");
    let ext = lowercase_ext(source_path);
    let mapping = mappings.get(&ext);
    let rel = if let Some(m) = mapping {
        if m.output_ext != ext {
            rel.with_extension(m.output_ext.strip_prefix('.').unwrap_or(&m.output_ext))
        } else {
            rel.to_path_buf()
        }
    } else {
        rel.to_path_buf()
    };
    target_base.join(rel)
}

fn build_matcher(root: &Path, patterns: &[String]) -> Gitignore {
    let mut b = GitignoreBuilder::new(root);
    for p in patterns {
        let _ = b.add_line(None, p);
    }
    b.build().unwrap_or_else(|_| Gitignore::empty())
}

fn is_excluded(matcher: &Gitignore, path: &Path, is_dir: bool) -> bool {
    matcher
        .matched_path_or_any_parents(path, is_dir)
        .is_ignore()
}

fn walk(root: &Path) -> (Vec<PathBuf>, Vec<PathBuf>) {
    let mut files = Vec::new();
    let mut dirs = Vec::new();
    let walker = ignore::WalkBuilder::new(root)
        .hidden(false)
        .ignore(false)
        .git_ignore(false)
        .git_global(false)
        .git_exclude(false)
        .parents(false)
        .require_git(false)
        .build();
    for entry in walker.flatten() {
        let path = entry.path();
        if path == root {
            continue;
        }
        let is_dir = entry.file_type().map(|t| t.is_dir()).unwrap_or(false);
        if is_dir {
            dirs.push(path.to_path_buf());
        } else {
            files.push(path.to_path_buf());
        }
    }
    files.sort();
    dirs.sort();
    (files, dirs)
}

fn copy_path_attr(source_meta: &std::fs::Metadata, target: &Path) -> std::io::Result<()> {
    std::fs::set_permissions(target, source_meta.permissions())?;
    let source_mtime = FileTime::from_last_modification_time(source_meta);
    // Preserve target's atime, set source's mtime
    let target_meta = std::fs::metadata(target)?;
    let target_atime = FileTime::from_last_access_time(&target_meta);
    filetime::set_file_times(target, target_atime, source_mtime)?;
    Ok(())
}

async fn sync_file(source: PathBuf, target: PathBuf, config: Arc<Config>, dry_run: bool, modify_window: i32) {
    let source_meta = match source.symlink_metadata() {
        Ok(m) => m,
        Err(_) => {
            tracing::warn!("File disappeared: {}", source.display());
            return;
        }
    };

    let source_mtime = FileTime::from_last_modification_time(&source_meta);
    if let Ok(target_meta) = target.symlink_metadata() {
        let target_mtime = FileTime::from_last_modification_time(&target_meta);
        let up_to_date = if modify_window < 0 {
            // Nanosecond precision
            target_mtime == source_mtime
        } else {
            // Second-level comparison with N-second tolerance
            target_mtime.unix_seconds().abs_diff(source_mtime.unix_seconds())
                <= modify_window as u64
        };
        if up_to_date {
            tracing::debug!("Up to date, skipping {}", target.display());
            return;
        }
        tracing::debug!(
            "Stale: {} (source mtime={}, target mtime={})",
            target.display(),
            source_mtime,
            target_mtime
        );
    } else {
        tracing::debug!("New: {}", target.display());
    }

    let ext = lowercase_ext(&source);
    let mapping = config.mappings.get(&ext);

    if dry_run {
        if mapping.is_some() {
            tracing::info!("Would convert {} -> {}", source.display(), target.display());
        } else if config.copy_unmatched {
            tracing::info!("Would copy {} -> {}", source.display(), target.display());
        }
        return;
    }

    if let Some(parent) = target.parent() {
        let _ = std::fs::create_dir_all(parent);
    }

    if let Some(mapping) = mapping {
        let conv = &config.converters[&mapping.converter];
        if !converter::convert(conv, &source, &target).await {
            return;
        }
    } else if config.copy_unmatched {
        tracing::info!("Copying {}", source.display());
        if let Err(e) = tokio::fs::copy(&source, &target).await {
            tracing::warn!("Failed to copy {} to {}: {}", source.display(), target.display(), e);
            return;
        }
    } else {
        return;
    }

    if let Err(e) = copy_path_attr(&source_meta, &target) {
        tracing::warn!("Failed to set attributes on {}: {}", target.display(), e);
    }
}

pub fn sanitize(config: &Config, known_targets: &HashSet<PathBuf>, known_dirs: &HashSet<PathBuf>) {
    if !config.target.is_dir() {
        return;
    }

    let matcher = build_matcher(&config.target, &config.target_exclude);

    let walker = ignore::WalkBuilder::new(&config.target)
        .hidden(false)
        .ignore(false)
        .git_ignore(false)
        .git_global(false)
        .git_exclude(false)
        .parents(false)
        .require_git(false)
        .filter_entry(move |e| {
            let is_dir = e.file_type().map(|t| t.is_dir()).unwrap_or(false);
            !is_excluded(&matcher, e.path(), is_dir)
        })
        .build();

    let mut files: Vec<PathBuf> = Vec::new();
    let mut dirs: Vec<PathBuf> = Vec::new();
    for entry in walker.flatten() {
        let path = entry.path();
        if path == config.target {
            continue;
        }
        let is_dir = entry.file_type().map(|t| t.is_dir()).unwrap_or(false);
        if is_dir {
            dirs.push(path.to_path_buf());
        } else {
            files.push(path.to_path_buf());
        }
    }
    files.sort();
    dirs.sort();

    for entry in files {
        if known_targets.contains(&entry) {
            continue;
        }
        tracing::info!("Deleting {}", entry.display());
        if let Err(e) = std::fs::remove_file(&entry) {
            tracing::warn!("Failed to delete {}: {}", entry.display(), e);
        }
    }

    dirs.reverse();
    for dir in dirs {
        if known_dirs.contains(&dir) {
            continue;
        }
        tracing::info!("Removing directory {}", dir.display());
        if let Err(e) = std::fs::remove_dir(&dir) {
            tracing::warn!("Failed to remove directory {}: {}", dir.display(), e);
        }
    }
}

pub async fn run(config: Config, dry_run: bool, modify_window: i32) -> anyhow::Result<()> {
    tracing::info!("Scanning \"{}\"", config.source.display());

    let jobs = if config.jobs > 0 {
        config.jobs
    } else {
        std::thread::available_parallelism()
            .map(|n| n.get())
            .unwrap_or(1)
    };

    let config = Arc::new(config);
    let mut known_targets = HashSet::new();
    let mut known_dirs = HashSet::new();

    let (source_files, source_dirs) = walk(&config.source);
    let source_matcher = build_matcher(&config.source, &config.source_exclude);

    // Collect work items before spawning so "Scanned N items" logs before task output
    let mut work_items: Vec<(PathBuf, PathBuf)> = Vec::new();
    for source_path in source_files {
        if is_excluded(&source_matcher, &source_path, false) {
            continue;
        }

        let ext = lowercase_ext(&source_path);
        if !config.mappings.contains_key(&ext) && !config.copy_unmatched {
            continue;
        }

        let target_path =
            build_target_path(&source_path, &config.source, &config.target, &config.mappings);
        known_targets.insert(target_path.clone());
        work_items.push((source_path, target_path));
    }

    for source_dir in source_dirs {
        if is_excluded(&source_matcher, &source_dir, true) {
            continue;
        }
        let rel_path = source_dir.strip_prefix(&config.source).unwrap();
        let target_dir = config.target.join(rel_path);
        known_dirs.insert(target_dir.clone());
        if dry_run {
            tracing::info!("Would create directory {}", target_dir.display());
        } else {
            std::fs::create_dir_all(&target_dir)?;
        }
    }

    tracing::info!("Scanned {} items", work_items.len());

    let cancelled = Arc::new(AtomicBool::new(false));
    let cancelled_signal = Arc::clone(&cancelled);
    tokio::spawn(async move {
        let _ = tokio::signal::ctrl_c().await;
        cancelled_signal.store(true, Ordering::Relaxed);
    });

    let semaphore = Arc::new(Semaphore::new(jobs));
    let mut join_set = JoinSet::new();

    for (source_path, target_path) in work_items {
        if cancelled.load(Ordering::Relaxed) {
            break;
        }
        let permit = semaphore.clone().acquire_owned().await.unwrap();
        let cfg = Arc::clone(&config);
        join_set.spawn(async move {
            sync_file(source_path, target_path, cfg, dry_run, modify_window).await;
            drop(permit);
        });
    }

    // Wait for in-flight tasks to finish so temp files are cleaned up
    while let Some(result) = join_set.join_next().await {
        result?;
    }

    if cancelled.load(Ordering::Relaxed) {
        tracing::info!("Interrupted");
        return Ok(());
    }

    if !dry_run {
        sanitize(&config, &known_targets, &known_dirs);
    }

    tracing::info!("Processing complete");

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::{Config, Converter, Mapping};
    use std::fs;

    fn make_config(source: PathBuf, target: PathBuf) -> Config {
        Config {
            source,
            target,
            copy_unmatched: true,
            source_exclude: vec![],
            target_exclude: vec![],
            jobs: 1,
            converters: HashMap::new(),
            mappings: HashMap::new(),
        }
    }

    #[tokio::test]
    async fn test_copies_unmatched_file() {
        let tmp = tempfile::tempdir().unwrap();
        let source = tmp.path().join("source");
        let target = tmp.path().join("target");
        fs::create_dir(&source).unwrap();
        fs::write(source.join("hello.txt"), "hello world").unwrap();

        let cfg = make_config(source, target.clone());
        run(cfg, false, 0).await.unwrap();

        assert_eq!(fs::read_to_string(target.join("hello.txt")).unwrap(), "hello world");
    }

    #[tokio::test]
    async fn test_copy_unmatched_false_skips_file() {
        let tmp = tempfile::tempdir().unwrap();
        let source = tmp.path().join("source");
        let target = tmp.path().join("target");
        fs::create_dir(&source).unwrap();
        fs::write(source.join("hello.txt"), "hello world").unwrap();

        let mut cfg = make_config(source, target.clone());
        cfg.copy_unmatched = false;
        run(cfg, false, 0).await.unwrap();

        assert!(!target.join("hello.txt").exists());
    }

    #[tokio::test]
    async fn test_copies_nested_directory_structure() {
        let tmp = tempfile::tempdir().unwrap();
        let source = tmp.path().join("source");
        let target = tmp.path().join("target");
        let sub = source.join("a").join("b");
        fs::create_dir_all(&sub).unwrap();
        fs::write(sub.join("deep.txt"), "deep").unwrap();

        let cfg = make_config(source, target.clone());
        run(cfg, false, 0).await.unwrap();

        assert_eq!(
            fs::read_to_string(target.join("a").join("b").join("deep.txt")).unwrap(),
            "deep"
        );
    }

    #[tokio::test]
    async fn test_mtime_skip() {
        let tmp = tempfile::tempdir().unwrap();
        let source = tmp.path().join("source");
        let target = tmp.path().join("target");
        fs::create_dir(&source).unwrap();
        fs::write(source.join("file.txt"), "v1").unwrap();

        let cfg = make_config(source.clone(), target.clone());
        run(cfg, false, 0).await.unwrap();

        let first_mtime = fs::metadata(target.join("file.txt"))
            .unwrap()
            .modified()
            .unwrap();
        let cfg = make_config(source, target.clone());
        run(cfg, false, 0).await.unwrap();
        let second_mtime = fs::metadata(target.join("file.txt"))
            .unwrap()
            .modified()
            .unwrap();
        assert_eq!(first_mtime, second_mtime);
    }

    #[tokio::test]
    async fn test_source_exclude() {
        let tmp = tempfile::tempdir().unwrap();
        let source = tmp.path().join("source");
        let target = tmp.path().join("target");
        fs::create_dir(&source).unwrap();
        fs::write(source.join("keep.txt"), "keep").unwrap();
        fs::write(source.join("skip.log"), "skip").unwrap();

        let mut cfg = make_config(source, target.clone());
        cfg.source_exclude = vec!["*.log".to_string()];
        run(cfg, false, 0).await.unwrap();

        assert!(target.join("keep.txt").exists());
        assert!(!target.join("skip.log").exists());
    }

    #[tokio::test]
    async fn test_orphan_cleanup() {
        let tmp = tempfile::tempdir().unwrap();
        let source = tmp.path().join("source");
        let target = tmp.path().join("target");
        fs::create_dir(&source).unwrap();
        fs::create_dir(&target).unwrap();
        fs::write(source.join("keep.txt"), "keep").unwrap();
        fs::write(target.join("orphan.txt"), "orphan").unwrap();

        let cfg = make_config(source, target.clone());
        run(cfg, false, 0).await.unwrap();

        assert!(target.join("keep.txt").exists());
        assert!(!target.join("orphan.txt").exists());
    }

    #[tokio::test]
    async fn test_target_exclude_protects_from_cleanup() {
        let tmp = tempfile::tempdir().unwrap();
        let source = tmp.path().join("source");
        let target = tmp.path().join("target");
        fs::create_dir(&source).unwrap();
        fs::create_dir(&target).unwrap();
        fs::write(source.join("keep.txt"), "keep").unwrap();
        fs::write(target.join("playlist.m3u"), "protected").unwrap();

        let mut cfg = make_config(source, target.clone());
        cfg.target_exclude = vec!["*.m3u".to_string()];
        run(cfg, false, 0).await.unwrap();

        assert!(target.join("keep.txt").exists());
        assert!(target.join("playlist.m3u").exists());
    }

    #[tokio::test]
    async fn test_target_exclude_protects_directory() {
        let tmp = tempfile::tempdir().unwrap();
        let source = tmp.path().join("source");
        let target = tmp.path().join("target");
        fs::create_dir(&source).unwrap();
        fs::create_dir(&target).unwrap();
        fs::create_dir(target.join(".stfolder")).unwrap();
        fs::write(target.join(".stfolder").join("marker"), "syncthing").unwrap();
        fs::write(source.join("keep.txt"), "keep").unwrap();

        let mut cfg = make_config(source, target.clone());
        cfg.target_exclude = vec![".stfolder/".to_string()];
        run(cfg, false, 0).await.unwrap();

        assert!(target.join("keep.txt").exists());
        assert!(target.join(".stfolder").is_dir());
        assert!(target.join(".stfolder").join("marker").exists());
    }

    #[tokio::test]
    async fn test_target_exclude_directory_no_trailing_slash() {
        let tmp = tempfile::tempdir().unwrap();
        let source = tmp.path().join("source");
        let target = tmp.path().join("target");
        fs::create_dir(&source).unwrap();
        fs::create_dir(&target).unwrap();
        fs::create_dir(target.join(".stfolder")).unwrap();
        fs::write(target.join(".stfolder").join("marker"), "x").unwrap();

        let mut cfg = make_config(source, target.clone());
        cfg.target_exclude = vec![".stfolder".to_string()];
        run(cfg, false, 0).await.unwrap();

        assert!(target.join(".stfolder").is_dir());
        assert!(target.join(".stfolder").join("marker").exists());
    }

    #[tokio::test]
    async fn test_target_exclude_anchored_only_top_level() {
        let tmp = tempfile::tempdir().unwrap();
        let source = tmp.path().join("source");
        let target = tmp.path().join("target");
        fs::create_dir(&source).unwrap();
        fs::create_dir(&target).unwrap();
        fs::create_dir(target.join(".stfolder")).unwrap();
        fs::write(target.join(".stfolder").join("m"), "x").unwrap();
        fs::create_dir_all(target.join("sub").join(".stfolder")).unwrap();
        fs::write(target.join("sub").join(".stfolder").join("m"), "x").unwrap();

        let mut cfg = make_config(source, target.clone());
        cfg.target_exclude = vec!["/.stfolder/".to_string()];
        run(cfg, false, 0).await.unwrap();

        assert!(target.join(".stfolder").is_dir());
        assert!(target.join(".stfolder").join("m").exists());
        assert!(!target.join("sub").join(".stfolder").exists());
    }

    #[tokio::test]
    async fn test_target_exclude_unanchored_any_depth() {
        let tmp = tempfile::tempdir().unwrap();
        let source = tmp.path().join("source");
        let target = tmp.path().join("target");
        fs::create_dir(&source).unwrap();
        fs::create_dir(&target).unwrap();
        fs::create_dir(target.join(".stfolder")).unwrap();
        fs::write(target.join(".stfolder").join("m"), "x").unwrap();
        fs::create_dir_all(target.join("sub").join(".stfolder")).unwrap();
        fs::write(target.join("sub").join(".stfolder").join("m"), "x").unwrap();

        let mut cfg = make_config(source, target.clone());
        cfg.target_exclude = vec![".stfolder/".to_string()];
        run(cfg, false, 0).await.unwrap();

        assert!(target.join(".stfolder").join("m").exists());
        assert!(target.join("sub").join(".stfolder").join("m").exists());
    }

    #[tokio::test]
    async fn test_source_exclude_anchored_top_level_only() {
        let tmp = tempfile::tempdir().unwrap();
        let source = tmp.path().join("source");
        let target = tmp.path().join("target");
        fs::create_dir(&source).unwrap();
        fs::write(source.join("skip.log"), "x").unwrap();
        fs::create_dir(source.join("sub")).unwrap();
        fs::write(source.join("sub").join("keep.log"), "x").unwrap();

        let mut cfg = make_config(source, target.clone());
        cfg.source_exclude = vec!["/*.log".to_string()];
        run(cfg, false, 0).await.unwrap();

        assert!(!target.join("skip.log").exists());
        assert!(target.join("sub").join("keep.log").exists());
    }

    #[tokio::test]
    async fn test_source_exclude_internal_slash_anchored() {
        let tmp = tempfile::tempdir().unwrap();
        let source = tmp.path().join("source");
        let target = tmp.path().join("target");
        fs::create_dir_all(source.join("a").join("b")).unwrap();
        fs::write(source.join("a").join("b").join("f.txt"), "x").unwrap();
        fs::create_dir_all(source.join("nested").join("a").join("b")).unwrap();
        fs::write(source.join("nested").join("a").join("b").join("f.txt"), "x").unwrap();

        let mut cfg = make_config(source, target.clone());
        cfg.source_exclude = vec!["a/b/f.txt".to_string()];
        run(cfg, false, 0).await.unwrap();

        assert!(!target.join("a").join("b").join("f.txt").exists());
        assert!(target.join("nested").join("a").join("b").join("f.txt").exists());
    }

    #[tokio::test]
    async fn test_source_exclude_negation() {
        let tmp = tempfile::tempdir().unwrap();
        let source = tmp.path().join("source");
        let target = tmp.path().join("target");
        fs::create_dir(&source).unwrap();
        fs::write(source.join("a.log"), "x").unwrap();
        fs::write(source.join("keep.log"), "x").unwrap();

        let mut cfg = make_config(source, target.clone());
        cfg.source_exclude = vec!["*.log".to_string(), "!keep.log".to_string()];
        run(cfg, false, 0).await.unwrap();

        assert!(!target.join("a.log").exists());
        assert!(target.join("keep.log").exists());
    }

    #[tokio::test]
    async fn test_dry_run_does_not_modify() {
        let tmp = tempfile::tempdir().unwrap();
        let source = tmp.path().join("source");
        let target = tmp.path().join("target");
        fs::create_dir(&source).unwrap();
        fs::write(source.join("file.txt"), "content").unwrap();

        let cfg = make_config(source, target.clone());
        run(cfg, true, 0).await.unwrap();

        assert!(!target.exists() || !target.join("file.txt").exists());
    }

    #[tokio::test]
    async fn test_converter_changes_extension() {
        let tmp = tempfile::tempdir().unwrap();
        let source = tmp.path().join("source");
        let target = tmp.path().join("target");
        fs::create_dir(&source).unwrap();
        fs::write(source.join("song.fake"), "audio data").unwrap();

        let mut cfg = make_config(source, target.clone());
        cfg.converters.insert(
            "copy-converter".to_string(),
            Converter {
                name: "copy-converter".to_string(),
                command: vec![
                    "cp".to_string(),
                    "{input}".to_string(),
                    "{output}".to_string(),
                ],
            },
        );
        cfg.mappings.insert(
            ".fake".to_string(),
            Mapping {
                converter: "copy-converter".to_string(),
                output_ext: ".out".to_string(),
            },
        );
        run(cfg, false, 0).await.unwrap();

        assert!(target.join("song.out").exists());
        assert_eq!(fs::read_to_string(target.join("song.out")).unwrap(), "audio data");
        assert!(!target.join("song.fake").exists());
    }

    #[tokio::test]
    async fn test_converter_keeps_extension_when_same() {
        let tmp = tempfile::tempdir().unwrap();
        let source = tmp.path().join("source");
        let target = tmp.path().join("target");
        fs::create_dir(&source).unwrap();
        fs::write(source.join("photo.jpg"), "image data").unwrap();

        let mut cfg = make_config(source, target.clone());
        cfg.converters.insert(
            "compress".to_string(),
            Converter {
                name: "compress".to_string(),
                command: vec![
                    "cp".to_string(),
                    "{input}".to_string(),
                    "{output}".to_string(),
                ],
            },
        );
        cfg.mappings.insert(
            ".jpg".to_string(),
            Mapping {
                converter: "compress".to_string(),
                output_ext: ".jpg".to_string(),
            },
        );
        run(cfg, false, 0).await.unwrap();

        assert!(target.join("photo.jpg").exists());
        assert_eq!(fs::read_to_string(target.join("photo.jpg")).unwrap(), "image data");
    }

    #[tokio::test]
    async fn test_copies_empty_directories() {
        let tmp = tempfile::tempdir().unwrap();
        let source = tmp.path().join("source");
        let target = tmp.path().join("target");
        fs::create_dir(&source).unwrap();
        fs::create_dir(source.join("empty_dir")).unwrap();
        fs::create_dir_all(source.join("nested").join("empty")).unwrap();

        let cfg = make_config(source, target.clone());
        run(cfg, false, 0).await.unwrap();

        assert!(target.join("empty_dir").is_dir());
        assert!(target.join("nested").join("empty").is_dir());
    }

    #[tokio::test]
    async fn test_empty_directories_survive_resync() {
        let tmp = tempfile::tempdir().unwrap();
        let source = tmp.path().join("source");
        let target = tmp.path().join("target");
        fs::create_dir(&source).unwrap();
        fs::create_dir(source.join("empty_dir")).unwrap();
        fs::write(source.join("file.txt"), "content").unwrap();

        let cfg = make_config(source.clone(), target.clone());
        run(cfg, false, 0).await.unwrap();
        let cfg = make_config(source, target.clone());
        run(cfg, false, 0).await.unwrap();

        assert!(target.join("empty_dir").is_dir());
        assert!(target.join("file.txt").exists());
    }

    #[tokio::test]
    async fn test_empty_source_directory() {
        let tmp = tempfile::tempdir().unwrap();
        let source = tmp.path().join("source");
        fs::create_dir(&source).unwrap();

        let cfg = make_config(source, tmp.path().join("target"));
        run(cfg, false, 0).await.unwrap();
    }

    #[tokio::test]
    async fn test_failed_converter_skips_file() {
        let tmp = tempfile::tempdir().unwrap();
        let source = tmp.path().join("source");
        let target = tmp.path().join("target");
        fs::create_dir(&source).unwrap();
        fs::write(source.join("file.bad"), "data").unwrap();

        let mut cfg = make_config(source, target.clone());
        cfg.converters.insert(
            "failing".to_string(),
            Converter {
                name: "failing".to_string(),
                command: vec!["false".to_string()],
            },
        );
        cfg.mappings.insert(
            ".bad".to_string(),
            Mapping {
                converter: "failing".to_string(),
                output_ext: ".out".to_string(),
            },
        );
        run(cfg, false, 0).await.unwrap();

        assert!(!target.join("file.out").exists());
    }
}
