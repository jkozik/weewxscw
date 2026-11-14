# weewxscw — Davis Vantage Vue via Davis Envoy + WiFiLogger (TCP).
# The Vantage driver is built into weewx, so nothing extra is needed; this
# Dockerfile exists so the image is pinned in one place and can grow later
# (extensions, pip packages) the same way weewxrtlsdr's does.
FROM felddy/weewx:5.5.6
USER root
# System timezone = the station's (TZ in docker-compose.yml). felddy/weewx
# leaves /etc/localtime at UTC; some skins/tools read it instead of $TZ.
RUN echo America/New_York > /etc/timezone \
    && ln -sf /usr/share/zoneinfo/America/New_York /etc/localtime
USER weewx
