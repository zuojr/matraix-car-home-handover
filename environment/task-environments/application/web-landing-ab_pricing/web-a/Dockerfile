FROM nginx:alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY site/ /usr/share/nginx/html/

# Directory for the collectable access log (see nginx.conf access_log path).
RUN mkdir -p /var/log/site

EXPOSE 80
