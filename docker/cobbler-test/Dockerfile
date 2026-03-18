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
    mod_wsgi \
    tftp-server \
    supervisor \
    python3-pyyaml \
    && dnf clean all

# Generate self-signed SSL certificate for Apache mod_ssl
RUN mkdir -p /etc/pki/tls/certs /etc/pki/tls/private && \
    openssl req -x509 -nodes -days 3650 \
      -newkey rsa:2048 \
      -keyout /etc/pki/tls/private/localhost.key \
      -out /etc/pki/tls/certs/localhost.crt \
      -subj "/CN=localhost"

# Ensure Cobbler WSGI config is in place for Apache
# The cobbler RPM provides /etc/httpd/conf.d/cobbler.conf and cobbler_web.conf
# If the RPM does not include WSGI config, create a minimal one
RUN if [ ! -f /etc/httpd/conf.d/cobbler.conf ]; then \
    echo 'WSGIScriptAlias /cobbler_api /usr/share/cobbler/web/cobbler.wsgi' > /etc/httpd/conf.d/cobbler.conf && \
    echo '<Directory /usr/share/cobbler/web/>' >> /etc/httpd/conf.d/cobbler.conf && \
    echo '  Require all granted' >> /etc/httpd/conf.d/cobbler.conf && \
    echo '</Directory>' >> /etc/httpd/conf.d/cobbler.conf; \
    fi

# Fix Apache PID file and log directory permissions
RUN mkdir -p /run/httpd && chown apache:apache /run/httpd

# Copy supervisor config
COPY supervisord.conf /etc/supervisord.d/cobbler.ini

EXPOSE 80 443

# Use supervisord to manage cobblerd and httpd
CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisord.conf"]
