FROM rockylinux:8

LABEL maintainer="baremetal-ops"
LABEL description="Cobbler 3.3.x test container for CI/CD"

# Enable PowerTools and EPEL repositories
RUN dnf install -y dnf-plugins-core epel-release && \
    dnf config-manager --set-enabled powertools && \
    dnf clean all

# Install Cobbler and dependencies
# Cobbler 3.3.x is available via EPEL for Rocky Linux 8
RUN dnf install -y \
    cobbler \
    httpd \
    mod_ssl \
    tftp-server \
    supervisor \
    python3-pyyaml \
    && dnf clean all

# Ensure Cobbler WSGI config is in place for Apache
# The cobbler RPM provides /etc/httpd/conf.d/cobbler.conf and cobbler_web.conf

# Copy supervisor config
COPY supervisord.conf /etc/supervisord.d/cobbler.ini

EXPOSE 80 443

# Use supervisord to manage cobblerd and httpd
CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisord.conf"]
