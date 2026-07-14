from setuptools import setup, find_packages

setup(
    name="streamget",
    version="4.0.8",
    packages=find_packages(),
    install_requires=[
        "aiohttp",
        "pycryptodome",
        "pycryptodomex",
        "execjs"
    ],
)
