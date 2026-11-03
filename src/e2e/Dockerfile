# Playwright with the test dependencies baked in; compose.e2e.yaml mounts
# the tests over /e2e and keeps this node_modules.
FROM mcr.microsoft.com/playwright:v1.64.1-noble

WORKDIR /e2e
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts

# Where compose.e2e.yaml mounts the outputs. Open to any user: the tests run
# as DOCKER_USER, and a new volume takes this folder's permissions.
RUN mkdir /e2e-output && chmod 777 /e2e-output
