mod config;
mod converter;
mod error;
mod substitute;
mod sync;

use std::path::PathBuf;

use clap::Parser;

#[derive(Parser)]
#[command(
    name = "harmonize",
    version,
    long_about = "Create and synchronize transcoded copies of audio folders.\n\n\
                  source_exclude and target_exclude in the config use \
                  gitignore pattern syntax."
)]
struct Cli {
    /// Config file path
    #[arg(long, required_unless_present = "stdin")]
    config: Option<PathBuf>,

    /// Read config from stdin
    #[arg(long)]
    stdin: bool,

    /// Number of parallel jobs
    #[arg(short = 'n')]
    jobs: Option<usize>,

    /// Suppress informational output
    #[arg(short = 'q', long = "quiet")]
    quiet: bool,

    /// Enable debug output
    #[arg(short = 'v', long = "verbose")]
    verbose: bool,

    /// Show what would be done without doing it
    #[arg(long)]
    dry_run: bool,

    /// Compare mod-times with reduced accuracy (seconds). -1 = nanoseconds.
    #[arg(long, default_value = "0", allow_hyphen_values = true)]
    modify_window: i32,
}

fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();

    let level = if cli.verbose {
        tracing::Level::DEBUG
    } else if cli.quiet {
        tracing::Level::WARN
    } else {
        tracing::Level::INFO
    };

    tracing_subscriber::fmt()
        .with_max_level(level)
        .with_target(false)
        .with_level(false)
        .with_ansi(false)
        .without_time()
        .with_writer(std::io::stderr)
        .init();

    let mut cfg = if cli.stdin {
        let mut buf = Vec::new();
        std::io::Read::read_to_end(&mut std::io::stdin(), &mut buf)?;
        config::load_bytes(&buf)?
    } else {
        config::load(cli.config.as_ref().unwrap())?
    };

    if let Some(jobs) = cli.jobs {
        cfg.jobs = jobs;
    }

    let rt = tokio::runtime::Runtime::new()?;
    rt.block_on(sync::run(cfg, cli.dry_run, cli.modify_window))?;

    Ok(())
}
