#setup cython code
from setuptools import setup, find_packages
from Cython.Build import cythonize
import numpy
import os
import codecs
def read(rel_path):
    here = os.path.abspath(os.path.dirname(__file__))
    with codecs.open(os.path.join(here, rel_path), 'r') as fp:
        return fp.read()

def get_version(rel_path):
    for line in read(rel_path).splitlines():
        if line.startswith('__version__'):
            delim = '"' if '"' in line else "'"
            return line.split(delim)[1]
    else:
        raise RuntimeError("Unable to find version string.")

setup(
	name="LoopStructural",
	install_requires=[
	# 'Cython',
	# 'numpy',
	# 'pandas',
	# 'scipy',
	# 'matplotlib',
	# # 'lavavu',
	# 'scikit-image',
	# 'scikit-learn'
	],
	version=get_version("LoopStructural/__init__.py"),
    packages=find_packages(),
	ext_modules=cythonize("LoopStructural/interpolators/cython/*.pyx",compiler_directives={"language_level": "3"}),
	include_dirs=[numpy.get_include()],
	include_package_data=True,
	package_data={'LoopStructural':['datasets/data/*.csv','datasets/data/*.txt']},
	)
