import setuptools

setuptools.setup(
    name='harmonize',
    version='0.1.5',
    author='Andrew Rabert',
    author_email='ar@nullsum.net',
    description='Create and synchronize transcoded copies of audio folders',
    long_description=open('DESCRIPTION.rst').read(),
    url='https://github.com/nvllsvm/harmonize',
    license='Apache 2.0',
    packages=['harmonize'],
    entry_points={
        'console_scripts': ['harmonize=harmonize:main']
    },
    classifiers=(
        'Development Status :: 4 - Beta',
        'Intended Audience :: End Users/Desktop',
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python :: 3 :: Only'
    ),
)
