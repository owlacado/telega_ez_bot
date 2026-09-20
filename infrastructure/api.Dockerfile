FROM python:3.13-slim
ARG APP_VERSION=0.3.0
ARG RELEASE_COMMIT=unknown
ENV APP_VERSION=$APP_VERSION
ENV RELEASE_COMMIT=$RELEASE_COMMIT
WORKDIR /app/apps/api
COPY apps/api/requirements.lock ./requirements.lock
RUN pip install --no-cache-dir -r requirements.lock
COPY apps/api/ ./
RUN pip install --no-cache-dir --no-deps . && useradd --create-home hub
USER hub
EXPOSE 8000
