import pathlib

import setuptools

REPO = pathlib.Path(__file__).parent

setuptools.setup(
    name='harmonize',
    version='1.0.2',
    author='Andrew Rabert',
    author_email='ar@nullsum.net',
    description='Create and synchronize transcoded copies of audio folders',
    long_description=REPO.joinpath('README.rst').read_text(),
    url='https://github.com/nvllsvm/harmonize',
    install_requires=['mutagen>=1.40.0'],
    license='Apache 2.0',
    packages=['harmonize'],
    entry_points={
        'console_scripts': ['harmonize=harmonize.__main__:main']
    },
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: End Users/Desktop',
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python :: 3 :: Only'
    ],
    python_requires='>=3.6'
)
