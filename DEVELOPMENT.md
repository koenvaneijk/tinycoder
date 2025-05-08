# Publish to PyPI
```bash
python setup.py sdist bdist_wheel
python -m twine upload dist/*
```