from fractions import Fraction

import av
import pytest


@pytest.fixture(scope="session")
def video_bytes(tmp_path_factory):
    path = tmp_path_factory.mktemp("media") / "sample.mp4"
    with av.open(str(path), "w") as out:
        video = out.add_stream("mpeg4", rate=24)
        video.width, video.height, video.pix_fmt = 64, 96, "yuv420p"
        audio = out.add_stream("aac", rate=48000)
        audio.layout = "stereo"
        for i in range(24):
            frame = av.VideoFrame(64, 96, "rgb24")
            for plane in frame.planes:
                plane.update(bytes(plane.buffer_size))
            frame.pts, frame.time_base = i, Fraction(1, 24)
            for packet in video.encode(frame):
                out.mux(packet)
        for i in range(47):
            frame = av.AudioFrame(format="fltp", layout="stereo", samples=1024)
            frame.sample_rate, frame.pts, frame.time_base = 48000, i * 1024, Fraction(1, 48000)
            for plane in frame.planes:
                plane.update(bytes(plane.buffer_size))
            for packet in audio.encode(frame):
                out.mux(packet)
        for stream in (video, audio):
            for packet in stream.encode(None):
                out.mux(packet)
    return path.read_bytes()
