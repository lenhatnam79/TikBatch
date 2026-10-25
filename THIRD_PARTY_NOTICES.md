# Thành phần bên thứ ba

TikBatch dùng các thành phần dưới đây, giữ quyền tác giả và giấy phép của từng dự án. Các thư viện không bị sửa đổi. Bản ứng dụng portable giữ các thư mục `.dist-info`, gồm LICENSE/NOTICE do gói wheel cung cấp; runtime giữ giấy phép từ bản phân phối Python. Mã nguồn và build script của TikBatch được bàn giao để có thể thay thế hoặc build lại các thư viện dùng chung.

| Thành phần | Giấy phép / nguồn |
|---|---|
| Python / python-build-standalone | PSF và giấy phép thư viện kèm theo; https://www.python.org/ ; https://github.com/astral-sh/python-build-standalone |
| PySide6 Essentials / Qt | LGPLv3/GPLv3/commercial, tùy thành phần; https://www.qt.io/licensing/open-source-lgpl-obligations ; https://code.qt.io/ |
| Shiboken6 | LGPLv3/GPLv3/commercial; https://code.qt.io/cgit/pyside/pyside-setup.git/ |
| yt-dlp | Unlicense cùng notices của dự án; https://github.com/yt-dlp/yt-dlp |
| Playwright | Apache-2.0; https://github.com/microsoft/playwright-python |
| HTTPX / HTTP Core | BSD-3-Clause; https://github.com/encode/httpx ; https://github.com/encode/httpcore |
| AnyIO / IDNA / h11 / certifi | Giấy phép trong metadata từng gói; https://pypi.org/ |
| curl-cffi / libcurl | MIT và giấy phép thành phần kèm theo; https://github.com/lexiforest/curl_cffi |
| CFFI / pycparser | MIT/BSD; https://pypi.org/project/cffi/ ; https://github.com/eliben/pycparser |
| PyAV / FFmpeg | BSD-3-Clause và LGPL/GPL theo build FFmpeg kèm wheel; https://github.com/PyAV-Org/PyAV ; https://ffmpeg.org/legal.html |
| greenlet / pyee / typing-extensions | Giấy phép trong metadata từng gói; https://pypi.org/ |

Chromium được Playwright tải riêng khi người dùng chọn cài trình duyệt; không nằm trong gói TikBatch bàn giao. Các thành phần phụ thuộc tiếp tục áp dụng giấy phép riêng. Xem LICENSE/NOTICE cụ thể trong runtime trước khi phân phối lại.
