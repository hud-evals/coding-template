# syntax=docker/dockerfile:1
FROM ubuntu:24.04 AS setup

# Update and install core dependencies (including working Chromium browser)
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends \
  vim \
  openssl \
  ca-certificates \
  curl \
  wget \
  sudo \
  bash \
  net-tools \
  novnc \
  x11vnc \
  xvfb \
  python3 \
  python3-pip \
  python3-dev \
  python3-tk \
  python3-wheel \
  python3-venv \
  xfce4 \
  locales \
  libpq5 \
  sqlite3 \
  dbus-x11 \
  xfce4-terminal \
  xfonts-base \
  xdotool \
  psmisc \
  scrot \
  imagemagick \
  pm-utils \
  build-essential \
  python-is-python3 \
  unzip \
  git \
  xauth \
  ffmpeg \
  nginx \
  apache2 \
  libapache2-mod-wsgi-py3 \
  gnupg \
  gpg \ 
  jq \
  build-essential \
  python3 \
  make \
  gcc \
  g++ \
  libcairo2-dev \
  libjpeg-turbo8-dev \
  libpng-dev \
  libwebp-dev \
  libtiff-dev \
  libgif-dev \
  libvips-dev \
  libgstreamer1.0-0 \
  libgtk-4-1 \
  libgraphene-1.0-0 \
  libwoff1 \
  libevent-2.1-7 \
  libgstreamer-plugins-base1.0-0 \
  libgstreamer-plugins-good1.0-0 \
  libgstreamer-gl1.0-0 \
  libgstreamer-plugins-bad1.0-0 \
  libavif16 \
  libenchant-2-2 \
  libsecret-1-0 \
  libhyphen0 \
  libmanette-0.2-0 \
  libgles2 \
  redis-server \
  postgresql-common \
  postgresql-16-pgvector \
  mkcert \
  ruby \
  rubygems-integration

RUN update-ca-certificates

# Install Chromium browser from Debian repos (has ARM64 support)
RUN mkdir -p /etc/apt/keyrings && \
    wget -q -O /etc/apt/keyrings/debian-archive-key.asc https://ftp-master.debian.org/keys/archive-key-12.asc && \
    echo 'deb [signed-by=/etc/apt/keyrings/debian-archive-key.asc] http://deb.debian.org/debian bookworm main' > /etc/apt/sources.list.d/debian.list && \
    apt-get update && \
    apt-get install -y chromium chromium-driver && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# disable sandboxing for chromium (won't run in docker)
RUN echo "export CHROMIUM_FLAGS=--no-sandbox" >> /etc/chromium.d/default-flags
# disable dns over https (so we can mock websites)
RUN mkdir -p /etc/chromium/policies/managed
# note that this is edited during startup to append insecure sites as secure
RUN echo '{ "DnsOverHttpsMode": "off", "DefaultPopupsSetting": 1, "SafeBrowsingProtectionLevel": 1 }' > /etc/chromium/policies/managed/policy.json

# install fakes3
RUN gem install fakes3 -v 0.2.5

WORKDIR /

# Install nvm for ubuntu user
USER ubuntu
ENV HOME=/home/ubuntu
ENV NVM_DIR=/home/ubuntu/.nvm

# configure git
RUN git config --global user.email "agent@example.com"
RUN git config --global user.name "mr agent"

# Install latest nvm (v0.39.7)
RUN curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash

# ========================= PROJECT SETUP =========================
# CUSTOMIZE THIS SECTION FOR YOUR PROJECT
# This example shows Node.js/TypeScript setup. Adapt for your tech stack.
# Examples: Python (pip/poetry), Java (Maven/Gradle), C++ (CMake), Rust (Cargo)
# =================================================================

# 0) Clone or copy your project repository
# Replace with your repo URL and credentials if needed
# ENV GITHUB_TOKEN_BASE64=[YOUR_GITHUB_TOKEN_BASE64]
# ENV GITHUB_USERNAME=[YOUR_GITHUB_USERNAME]
# Example for private repo:
# RUN cd /home/ubuntu && \
#     GITHUB_TOKEN=$(echo "$GITHUB_TOKEN_BASE64" | base64 -d); \
#     git clone https://${GITHUB_USERNAME}:${GITHUB_TOKEN}@github.com/your-org/your-repo /home/ubuntu/[PROJECT_NAME]
# Example for public repo:
# RUN git clone https://github.com/your-org/your-repo /home/ubuntu/[PROJECT_NAME]

WORKDIR /home/ubuntu/[PROJECT_NAME]

# Checkout branches for testing (baseline, test, golden)
ARG TEST_BRANCH=[test_branch_name]
ARG GOLDEN_BRANCH=[golden_branch_name]
ARG BASELINE_BRANCH=[baseline_branch_name]
RUN git checkout $BASELINE_BRANCH && \
    git checkout $TEST_BRANCH && \
    git checkout $GOLDEN_BRANCH && \
    git checkout $BASELINE_BRANCH

# Generate patches for grading
USER root
RUN mkdir -p /home/root && \
    sudo -u ubuntu git diff $BASELINE_BRANCH $TEST_BRANCH > /home/root/test.patch && \
    sudo -u ubuntu git diff $BASELINE_BRANCH $GOLDEN_BRANCH > /home/root/golden.patch
USER ubuntu

# Overwrite git history to avoid leaking info
RUN rm -rf .git && git init && git add . && git commit -m "Initial commit"

# 1) Install language runtime/compiler
# === FOR NODE.JS/TYPESCRIPT (example) ===
# RUN NODE_VERSION_SPEC=$(jq -r '.engines.node // ""' /home/ubuntu/[PROJECT_NAME]/package.json) && \
#     NODE_VERSION=$(printf "%s" "$NODE_VERSION_SPEC" | grep -oE '<= *[0-9]+' | tail -n1 | sed -E 's/^[^0-9]*//') && \
#     if [ -z "$NODE_VERSION" ]; then NODE_VERSION=$(printf "%s" "$NODE_VERSION_SPEC" | grep -oE '[0-9]+' | tail -n1); fi && \
#     bash -c "source ~/.nvm/nvm.sh --no-use && nvm install $NODE_VERSION && nvm use $NODE_VERSION && nvm alias default $NODE_VERSION" && \
#     echo "source ~/.nvm/nvm.sh" >> /home/ubuntu/.bash_profile
# SHELL ["/bin/bash", "--login", "-c"]
#
# === FOR PYTHON ===
# RUN python3 -m pip install --upgrade pip
#
# === FOR JAVA ===
# RUN apt-get install -y openjdk-[version]-jdk maven
#
# === FOR C++ ===
# Already installed: gcc, g++, cmake via build-essential
#
# === FOR RUST ===
# RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y

# 2) Install build tool / package manager
# === FOR NODE.JS ===
# RUN YARN_VERSION=[version] && \
#     YARN_MAJOR=$(echo $YARN_VERSION | cut -d. -f1) && \
#     bash -lc "if [ \"$YARN_MAJOR\" -ge 2 ]; then \
#         corepack enable && corepack prepare yarn@$YARN_VERSION --activate; \
#     else \
#         npm install -g yarn@$YARN_VERSION; \
#     fi"
#
# === FOR PYTHON ===
# RUN pip install poetry  # or: pipenv, pip-tools
#
# === FOR JAVA ===
# Already installed: maven or gradle
#
# === FOR RUST ===
# Already installed with rustup

# 3) Install dependencies
# RUN cd /home/ubuntu/[PROJECT_NAME] && [INSTALL_DEPENDENCIES_COMMAND]
# Examples:
#   Node.js: yarn install
#   Python: pip install -r requirements.txt  or  poetry install
#   Java: mvn dependency:resolve
#   Rust: cargo fetch
#   C++: (usually handled by build system)

# 4) Configure test framework for JUnit XML output
# The grading system requires JUnit XML format for test results.
# Configure your test framework to output JUnit XML.
#
# === FOR JEST (Node.js) ===
# RUN cd /home/ubuntu/[PROJECT_NAME] && \
#     yarn add jest-junit && \
#     jq '.reporters = ["default", ["jest-junit", {"outputDirectory": "./", "outputName": "jest_results.xml"}]]' .jestconfig.json > .jestconfig.tmp && \
#     mv .jestconfig.tmp .jestconfig.json
#
# === FOR PYTEST (Python) ===
# RUN pip install pytest-junit && \
#     echo "[tool.pytest.ini_options]" >> pyproject.toml && \
#     echo "junit_family = 'xunit2'" >> pyproject.toml
#
# === FOR JUNIT (Java) ===
# Add to pom.xml or build.gradle:
#   <plugin>
#     <artifactId>maven-surefire-plugin</artifactId>
#     <configuration>
#       <reportsDirectory>./junit-results</reportsDirectory>
#     </configuration>
#   </plugin>
#
# === FOR GTEST (C++) ===
# Use gtest_junit_output: --gtest_output=xml:test_results.xml

# 5) Build the project
# RUN cd /home/ubuntu/[PROJECT_NAME] && [BUILD_COMMAND]
# Examples:
#   Node.js: yarn build  or  npm run build
#   Python: (often no build step)  or  python setup.py build
#   Java: mvn package -DskipTests
#   Rust: cargo build --release
#   C++: mkdir build && cd build && cmake .. && make

# 6) Configure environment files
# Copy and customize your environment configuration
COPY build_scripts/ /build_scripts/
RUN python3 /build_scripts/alter_env_files.py

# === End of PROJECT SETUP section ===

# Set environment variables
ENV HOME=/home/ubuntu \
    DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:1.0 \
    DISPLAY_WIDTH=1280 \
    DISPLAY_HEIGHT=800

EXPOSE 6080

# supress AT-SPI errors
ENV NO_AT_BRIDGE=1
USER root

# allow any user to run mkcert by inserting a script that calls sudo mkcert
RUN mv /usr/bin/mkcert /usr/bin/mkcert2 && \
    echo '#!/bin/bash\nexec sudo mkcert2 "$@"' > /usr/bin/mkcert && \
    chmod +x /usr/bin/mkcert
# add a line to sudoers file so that any user can run mkcert2 with sudo
RUN echo "ubuntu ALL=(ALL) NOPASSWD: /usr/bin/mkcert2" >> /etc/sudoers

# Setup and start dinit
COPY dinit.d/ /etc/dinit.d/
RUN mkdir -p /var/log/dinit && chmod 755 /var/log/dinit

# Copy postgres init scripts (SQL and shell)
COPY docker-entrypoint-initdb.d/ /docker-entrypoint-initdb.d/

# Postgres config:
ENV POSTGRES_USER=ubuntu
ENV POSTGRES_PASSWORD=ubuntu
ENV POSTGRES_DB=ubuntu

# ================================ hud evals mcp server setup ================================================
FROM setup AS runtime

# prepare for the hud evals mcp server
RUN pip install uv --break-system-packages

# copy python files
COPY ./src /mcp_server/src
COPY ./pyproject.toml /mcp_server/pyproject.toml
COPY ./README.md /mcp_server/README.md

ENV RUST_LOG=warn
RUN cd /mcp_server && uv venv && . .venv/bin/activate && uv sync && uv pip install -e . 
ENV PYTHONPATH=/mcp_server/.venv/lib/python3.10/site-packages
ENV PATH=/mcp_server/.venv/bin:$PATH

ENV WIDTH=1280
ENV HEIGHT=800
ENV DISPLAY_NUM=1
RUN mkdir -p /home/ubuntu/screenshots
RUN chmod 777 /home/ubuntu/screenshots
ENV SCREENSHOT_DIR=/home/ubuntu/screenshots
RUN mkdir -p /home/ubuntu/Downloads
RUN chmod 777 /home/ubuntu/Downloads

RUN chmod 777 /root

EXPOSE 6080 3000

ARG HINTS="none"
ENV HINTS=$HINTS

ARG PROBLEM_ID
ENV PROBLEM_ID=$PROBLEM_ID

CMD ["tail", "-f", "/dev/null"]