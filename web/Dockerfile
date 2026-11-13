# Browser build of the Expo app (the "preview" engine: same documents as
# Couchbase Lite, synced over the backend's REST /api/sync). Prebuilt into
# dist.tgz by `npm run export:web:docker` in ../mobile so this image needs no
# Node toolchain. ADD unpacks the archive.
FROM nginx:1.27.3-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
ADD dist.tgz /usr/share/nginx/html/
# The story that opens the demo: http://<host>:8084/story
COPY story.html /usr/share/nginx/html/story.html
# Files checked out or built on a workstation can carry 0600 modes; nginx's
# worker runs as `nginx` and would answer 403. Normalize everything it serves.
RUN chmod -R a+rX /usr/share/nginx/html
EXPOSE 80
