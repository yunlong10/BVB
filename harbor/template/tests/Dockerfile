# Verifier image for a BVB video-reconstruction task (separate from the agent).
# Blender 4.2 renders the submitted scene from its own animated camera; the grader
# then asks the judge model the held-back questions on the render. The questions,
# the judge's fixed answers on the source video, and the grader are baked at
# /opt/grader and never shipped to the agent.
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

# Judge client + frame sampling. Pinned.
RUN python3 -m pip install --no-cache-dir "openai==2.54.0" "opencv-python-headless==4.11.0.86" \
    && python3 -c "import cv2, openai; print('verifier runtime ok: openai', openai.__version__, 'cv2', cv2.__version__)"

# Headless EEVEE needs a display: the renderer calls Blender through this wrapper.
RUN printf '#!/bin/bash\nexec xvfb-run -a /opt/blender/blender "$@"\n' > /usr/local/bin/blender_xvfb \
    && chmod +x /usr/local/bin/blender_xvfb
ENV BLENDER_BIN=/usr/local/bin/blender_xvfb

WORKDIR /app
COPY grader/ /opt/grader/
# Harbor runs /tests/test.sh in the verifier container.
COPY . /tests/
RUN chmod +x /tests/test.sh
