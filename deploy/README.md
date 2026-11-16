# Model hosting

The root `Dockerfile` starts the existing recommender through Gunicorn using this folder's configuration.

Read [deployment](../guides/deployment.md) for artifact mounting and the website connection. Read [getting started](../guides/getting-started.md) before transferring a completed local run.

The container image contains source code. The trained artifacts are mounted separately. Do not assume the model is hosted because the source image builds.
