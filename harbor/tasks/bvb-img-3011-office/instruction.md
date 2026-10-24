Reconstruct the indoor scene in the video at /app/video.mp4 as an animated Blender scene, and save it to /app/result.blend.

The video is a 24.3-second handheld recording (360x640, 30 fps) of a camera moving through a real room. Your scene should let someone who has never seen the video understand what the room contains and how the camera moved through it: the objects, how many there are, their sizes, where they sit relative to each other, and what the camera looks at, in what order.

**How to look at the video**: Blender 4.2, Python 3, and FFmpeg are installed. Extract frames with FFmpeg (for example `ffmpeg -ss 4.5 -i /app/video.mp4 -frames:v 1 /app/frames/f_04.5.png`) and look at as many as you need; check details again while you build. Run Blender headless with `blender_run --python /app/build.py` (it wraps `xvfb-run -a blender --background`), and render test frames from your camera to compare with the video.

**Scene rules** (follow them exactly):
- Save the final scene to /app/result.blend as a regular file, not a symlink, for example `bpy.ops.wm.save_as_mainfile(filepath="/app/result.blend")`.
- Build all geometry from basic primitives only (cube, plane, cylinder, cone, uv_sphere, torus) and assemblies of them. Multi-part objects (a chair = seat + back + legs) are encouraged; group each object's parts in a Collection named after the object.
- No imported models, no sculpting or arbitrary meshes, no geometry nodes, particles, physics, or image textures. Materials are a single Principled BSDF with numeric values only.
- 1 Blender unit = 1 meter. Keep Unit Scale = 1.0. Use radians for rotations.
- Include at least one light and one camera, set the camera as the scene camera, and build the scene from at least 10 mesh objects.
- Reproduce object counts, sizes, positions, and spatial relationships as faithfully as you can from the video.

**Camera trajectory** (do not skip this): the video is a moving camera. Reconstruct that motion as an animation of the scene camera, not a single static viewpoint. Insert keyframes for the camera's `location` and `rotation_euler` over time and set `scene.frame_start` / `scene.frame_end` to span the motion, so that playing the scene's timeline from start to end retraces the video from start to end. When keying rotations, keep consecutive angles continuous (no jumps across ±180°), or the camera will spin the long way round between keys.

**Grading**: the grader gives 0 if /app/result.blend is missing, is a symlink, doesn't open in Blender 4.2, has no scene camera, or has fewer than 10 mesh objects. Otherwise it renders 16 frames from your scene camera across the timeline and asks a vision judge held-back questions about the room: what objects are there, where they are, and what the camera looks at and when. Only questions the judge answers correctly on the original video count; your reward is the share of those it still answers correctly from your render.

**Scope**: Solve only the reconstruction task described above. Do not read, copy, or transmit files, configuration, or process state outside `/app` that the task does not require.

You have 60 minutes to complete this task. Do not cheat by using online solutions or hints specific to this task.
