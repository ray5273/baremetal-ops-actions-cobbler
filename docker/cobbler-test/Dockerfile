FROM ubuntu:22.04

LABEL maintainer="baremetal-ops"
LABEL description="Cobbler 3.3.x test container for CI/CD"

ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    apache2 \
    libapache2-mod-wsgi-py3 \
    tftpd-hpa \
    supervisor \
    openssl \
    rsync \
    gcc \
    libsasl2-dev \
    libldap2-dev \
    libssl-dev \
    apache2-dev \
    && rm -rf /var/lib/apt/lists/*

# Install cobbler via pip
# Pin setuptools to avoid install_layout issue with Cheetah3/mod-wsgi
RUN pip3 install --no-cache-dir 'setuptools<67' wheel && \
    pip3 install --no-cache-dir \
      --trusted-host pypi.org --trusted-host files.pythonhosted.org \
      cobbler==3.3.7

# Create all required cobbler directories
RUN mkdir -p /etc/cobbler/boot_loader_conf \
    /var/lib/cobbler/collections/distros \
    /var/lib/cobbler/collections/profiles \
    /var/lib/cobbler/collections/systems \
    /var/lib/cobbler/collections/repos \
    /var/lib/cobbler/collections/images \
    /var/lib/cobbler/collections/mgmtclasses \
    /var/lib/cobbler/collections/packages \
    /var/lib/cobbler/collections/files \
    /var/lib/cobbler/collections/menus \
    /var/lib/cobbler/snippets \
    /var/lib/cobbler/templates \
    /var/lib/cobbler/loaders \
    /var/lib/cobbler/triggers/sync/pre \
    /var/lib/cobbler/triggers/sync/post \
    /var/lib/cobbler/triggers/install/pre \
    /var/lib/cobbler/triggers/install/post \
    /var/log/cobbler/tasks \
    /var/www/cobbler/distro_mirror \
    /var/www/cobbler/images \
    /var/www/cobbler/links \
    /var/www/cobbler/pub \
    /var/www/cobbler/repo_mirror \
    /var/lib/tftpboot/images \
    /var/lib/tftpboot/pxelinux.cfg \
    /var/lib/tftpboot/grub \
    /usr/share/cobbler/web && \
    touch /var/log/cobbler/cobbler.log

# Copy cobbler config files (from official cobbler v3.3.7 source)
COPY config/settings.yaml /etc/cobbler/settings.yaml
COPY config/modules.conf /etc/cobbler/modules.conf
COPY config/users.conf /etc/cobbler/users.conf
COPY config/users.digest /etc/cobbler/users.digest
COPY config/distro_signatures.json /var/lib/cobbler/distro_signatures.json
COPY config/boot_loader_conf/ /etc/cobbler/boot_loader_conf/

# Create cobbler version file (required by settings migration)
RUN printf '[cobbler]\ngitdate = Thu Jan 01 00:00:00 2023 +0000\ngitstamp = 0000000\nbuilddate = Thu Jan 01 00:00:00 2023\nversion = 3.3.7\nversion_tuple = [3, 3, 7]\n' \
    > /etc/cobbler/version

# Enable auto_migrate and fix tftpboot path placeholder in settings
RUN sed -i 's/auto_migrate_settings: false/auto_migrate_settings: true/' /etc/cobbler/settings.yaml && \
    sed -i 's|@@tftproot@@|/var/lib/tftpboot|g' /etc/cobbler/settings.yaml

# Generate self-signed SSL certificate for Apache
RUN mkdir -p /etc/pki/tls/certs /etc/pki/tls/private && \
    openssl req -x509 -nodes -days 3650 \
      -newkey rsa:2048 \
      -keyout /etc/pki/tls/private/localhost.key \
      -out /etc/pki/tls/certs/localhost.crt \
      -subj "/CN=localhost"

# Setup WSGI proxy for cobbler_api endpoint
COPY cobbler-api.wsgi /usr/share/cobbler/web/cobbler.wsgi
RUN printf 'WSGIScriptAlias /cobbler_api /usr/share/cobbler/web/cobbler.wsgi\n<Directory /usr/share/cobbler/web>\n  Require all granted\n</Directory>\n' \
      > /etc/apache2/conf-available/cobbler.conf && \
    a2enconf cobbler && \
    a2enmod wsgi ssl

# Copy supervisor config
COPY supervisord.conf /etc/supervisor/conf.d/cobbler.conf

EXPOSE 80 443

CMD ["/usr/bin/supervisord", "-n"]
