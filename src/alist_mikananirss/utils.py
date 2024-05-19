def is_video(filename):
    video_ext = [".mp4", ".mkv", ".avi", ".flv", ".mov", ".wmv", ".webm"]
    return any(filename.endswith(ext) for ext in video_ext)
