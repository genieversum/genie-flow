from setuptools import setup, find_packages

setup(
    name='genie_flow',
    version='$CI_COMMIT_TAG',
    description='TODO',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url='https://gitlab.com/your_username/your_project',
    author='Willem Van Asperen',
    author_email='willem.van.asperen@paconsulting.com',
    license='MIT',  # Or any other license
    packages=find_packages(),
    install_requires=[
        'python-statemachine',
        'pydantic~=2.7.1',
        'pydantic-redis',
        'jinja2~=3.1.4',
        'loguru~=0.7.2',
        'fastapi~=0.111.0',
        'celery~=5.4.0',
        'redis',
        'python-redis-lock~=4.0.0',
        'openai~=1.28.1',
        'PyYAML~=6.0.1',
        'requests~=2.31.0',
        'dependency-injector'
    ],
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.6',
)
