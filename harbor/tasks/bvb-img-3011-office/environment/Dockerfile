# Agent image for a BVB video-reconstruction task: Blender 4.2 + Xvfb + FFmpeg, with
# the source video baked in at /app/video.mp4. The questions, the reference scene,
# and the grader live only in the verifier image (tests/Dockerfile).
#
# The first layers match sandbox/Dockerfile in the BVB repo, so a machine that has
# built bvb-sandbox reuses them. Pinned to linux/amd64: Blender ships Linux
# prebuilts for x86-64 only, so on Apple Silicon the image runs under emulation.
FROM --platform=linux/amd64 ubuntu:22.04

ARG BLENDER_MAJOR=4.2
ARG BLENDER_VERSION=4.2.0
ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        xz-utils \
        xvfb \
        xauth \
        ffmpeg \
        python3 \
        python3-pip \
        libgl1-mesa-glx \
        libxi6 \
        libxrender1 \
        libxxf86vm1 \
        libxfixes3 \
        libxkbcommon0 \
        libsm6 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Blender LTS (Linux x64 prebuilt). Pinned for reproducibility.
RUN curl -fSL "https://download.blender.org/release/Blender${BLENDER_MAJOR}/blender-${BLENDER_VERSION}-linux-x64.tar.xz" \
        -o /tmp/blender.tar.xz \
    && mkdir -p /opt/blender \
    && tar -xf /tmp/blender.tar.xz -C /opt/blender --strip-components=1 \
    && rm /tmp/blender.tar.xz \
    && ln -s /opt/blender/blender /usr/local/bin/blender

# Blender 4.2's EEVEE needs EGL; Mesa's software drivers render without a GPU.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libegl1 \
        libegl-mesa0 \
        libgl1-mesa-dri \
        libglx-mesa0 \
    && rm -rf /var/lib/apt/lists/*

# Helper packages an agent's bpy scripts might use.
RUN python3 -m pip install --no-cache-dir numpy Pillow

# `blender_run` wraps xvfb so headless renders (EEVEE) work without a display.
RUN printf '#!/bin/bash\nexec xvfb-run -a blender --background "$@"\n' > /usr/local/bin/blender_run \
    && chmod +x /usr/local/bin/blender_run

WORKDIR /app
COPY video.mp4 /app/video.mp4
