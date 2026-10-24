FROM mcr.microsoft.com/playwright/python:v1.49.1-noble

WORKDIR /app

# The base image ships the browsers but not the playwright pip package, so it
# must be installed. --trusted-host lets the install succeed behind corporate
# TLS-intercepting proxies whose root CA isn't in the build image's trust store
# (otherwise pip fails with SSL: CERTIFICATE_VERIFY_FAILED against pypi).
RUN pip install --no-cache-dir \
    --trusted-host pypi.org \
    --trusted-host files.pythonhosted.org \
    --trusted-host pypi.python.org \
    playwright==1.49.1

RUN mkdir -p /app/input /app/output
