import setuptools

import harmonize


setuptools.setup(
    name='harmonize',
    version=harmonize.__version__,
    author='Andrew Rabert',
    author_email='ar@nullsum.net',
    description='Create and synchronize transcoded copies of audio folders',
    long_description=open('README.rst').read(),
    url='https://github.com/nvllsvm/harmonize',
    install_requires=['mutagen>=1.40.0'],
    license='Apache 2.0',
    packages=['harmonize'],
    entry_points={
        'console_scripts': ['harmonize=harmonize.app:main']
    },
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: End Users/Desktop',
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python :: 3 :: Only'
    ],
)
