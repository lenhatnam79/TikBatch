# TikBatch 0.2 — chạy ngầm và tải song song

Ứng dụng tải video theo kênh TikTok, chạy trên máy, không dùng API trả phí.

**Mã nguồn:** [github.com/lenhatnam79/TikBatch](https://github.com/lenhatnam79/TikBatch). Bản 0.2 mặc định chạy Chromium ngầm, tái sử dụng tab, tăng mức song song và phân loại lỗi để tránh làm chậm toàn bộ hàng đợi. Chỉ nút **Mở TikTok / Đăng nhập** chủ động mở cửa sổ; nếu nguồn yêu cầu xác minh, lượt tải dừng và giữ hàng đợi.

**Trạng thái:** 54 kiểm thử nội bộ đã qua. Chưa có benchmark chứng minh tốc độ Internet nhanh hơn hay tải hết kênh; phần nguồn TikTok vẫn phụ thuộc trạng thái truy cập và cần thử thực tế. Xem [báo cáo 0.2](BAO-CAO-0.2.md).

## Cách chạy

### macOS Apple Silicon — bản ứng dụng kèm theo

1. Giải nén `TikBatch-0.2-macOS-AppleSilicon.zip` và mở ứng dụng mới bên trong. Bản này kèm Python và thư viện; không cần cài Python riêng.
2. Chọn **Cài trình duyệt (lần đầu)** để tải Chromium miễn phí. Cần Internet.
3. Giữ link mẫu hoặc nhập link kênh khác, chọn thư mục lưu rồi chọn **Bắt đầu / Tiếp tục**.
4. Giữ **Chạy ngầm** bật. Nếu ứng dụng báo cần xác minh/đăng nhập, bấm **Mở TikTok / Đăng nhập**, hoàn tất rồi đóng cửa sổ và chọn **Bắt đầu / Tiếp tục**. Không cần mở trình duyệt liên tục khi tải.

Nâng cấp từ 0.1: dừng và đóng app cũ trước; mở app 0.2, chọn đúng thư mục cha đã dùng trước đó. Hàng đợi cũ được nâng cấp tự động; file thành công được bỏ qua. Không xóa `.tikbatch.sqlite3` hay thư mục phiên đăng nhập.

Bản ứng dụng chưa có chữ ký Developer ID/notarization. Nếu macOS chặn mở, xem nguồn gói và dùng mục Privacy & Security → Open Anyway nếu bạn quyết định cho phép. Không cần tắt Gatekeeper toàn hệ thống.

Mục tiêu bản kèm theo: macOS 13 trở lên, Apple Silicon. Đã kiểm tra khởi tạo giao diện bằng chế độ offscreen; chưa kiểm thử tương tác desktop đầy đủ. Mac Intel dùng mã nguồn hoặc build trên máy Intel.

### Windows — chạy từ mã nguồn

1. Cài **Python 3.12, 64-bit** từ [python.org](https://www.python.org/downloads/), gồm Python Launcher.
2. Giải nén mã nguồn vào thư mục có quyền ghi và mở `Start-Windows.cmd`.
3. Lần đầu, script tạo `.venv` và cài các thư viện miễn phí qua Internet.
4. Trong ứng dụng, chọn **Cài trình duyệt (lần đầu)**, sau đó nhập kênh và thư mục.

GitHub Actions tự kiểm thử và build khi có commit trên `main`. Khi job Windows thành công, tải artifact trong [Actions](https://github.com/lenhatnam79/TikBatch/actions), giải nén ZIP bên trong và mở `TikBatch.exe`. Kết quả job cụ thể được ghi trong báo cáo bàn giao; có workflow không đồng nghĩa build đã thành công.

### Chạy bằng Python trên hai hệ điều hành

Yêu cầu Python 3.11 hoặc 3.12; khuyến nghị 3.12.

```shell
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS: source .venv/bin/activate
python -m pip install -e .
python -m playwright install chromium
python -m tikbatch
```

macOS có Python 3.12 cũng có thể mở `Start-macOS.command`. Chạy bằng terminal nếu cần xem lỗi cài đặt.

CLI (từ mã nguồn):

```shell
python -m tikbatch --url "https://www.tiktok.com/@hong_le_" --output "/duong/dan/thu-muc" --max-concurrent 16
```

Trên Windows thay đường dẫn bằng dạng `D:\Videos`. CLI trả mã khác 0 nếu có lỗi tải hoặc chưa quét tới cuối nguồn; Ctrl+C lưu tiến độ rồi dừng.

CLI mặc định chạy ngầm. Chỉ thêm `--show-browser` khi muốn chủ động hiện cửa sổ để chẩn đoán. Mức `--max-concurrent` hỗ trợ 1–32.

## Hành vi tải

- Tạo thư mục con theo tên kênh trong thư mục bạn chọn.
- Quét trực tiếp bằng yt-dlp trước; nếu không được, dùng Chromium chạy ngầm với phiên truy cập riêng của ứng dụng. Không tự chuyển sang cửa sổ hiển thị khi lỗi.
- Vừa tìm danh sách vừa tải. Đường dẫn tải chỉ được chuẩn bị cho các video đang tới lượt, không chuẩn bị cả nghìn URL từ đầu.
- Khởi đầu tối đa 8 tác vụ video, tự điều chỉnh trong giới hạn người dùng chọn (1–32, mặc định 16). Tối đa 8 tác vụ lấy nguồn và 4 tab ngầm lấy chi tiết; các giới hạn nhỏ hơn được áp dụng nếu người dùng chọn ít tác vụ hơn.
- Một browser context được tái sử dụng cho cả lượt chạy. Nhóm tab chi tiết được tái sử dụng; không tạo cửa sổ mới theo từng video. Không tải hình/âm thanh phát trực tiếp, ảnh hoặc font trong quá trình lấy metadata.
- Thử lấy HTML dùng chung cookie trước; nếu không có dữ liệu phù hợp, bỏ đường này và dùng nhóm tab. Hỗ trợ cả universal data và SIGI_STATE, PlayAddrStruct và URL nguồn dự phòng có cùng thông số chất lượng.
- Đánh giá thông lượng mỗi 10 giây; lỗi mạng/giới hạn nguồn làm giảm mức song song, lỗi metadata của một video không làm giảm toàn bộ hàng đợi. Chưa được tối ưu bằng benchmark TikTok thật.
- Lỗi mạng dùng lại nguồn còn hạn. Lỗi URL bị từ chối thử CDN tương đương rồi làm mới nguồn ngay một lần trong tác vụ, không mặc định mở lại trang ở mọi lần thử.
- Nguồn có thời hạn ký còn hợp lệ được giữ tới gần thời điểm hết hạn; nguồn không có thông tin hết hạn dùng cache tối đa 30 phút.
- Khi nguồn trả 429/503, tạm ngừng cấp tác vụ mới theo Retry-After; các file đang tải vẫn có thể tiếp tục. Tối đa 4 lần thử mỗi video trong một lượt chạy.
- File tải dở dùng `.part`. Chỉ tiếp tục từ byte cũ khi có validator và HTTP Range khớp; nếu máy chủ không hỗ trợ, tải lại file đó.
- Xác nhận số byte khi nguồn cung cấp độ dài; mở container, kiểm tra luồng hình/âm thanh, giải mã khung hình đầu và tính SHA-256 trước khi chốt file. Không giải mã toàn bộ video.
- Giữ nguyên dữ liệu nguồn, không chuyển mã, không nâng độ phân giải, không xóa logo bằng crop hoặc AI.
- Chọn nguồn MP4 phát trực tiếp phù hợp, loại nguồn bị đánh dấu watermark, nguồn download không rõ logo, video-only và codec bytevc2. Không có bộ phát hiện logo theo hình ảnh; nguồn playback vẫn cần đối chiếu mẫu thật.
- “Chất lượng tốt nhất truy cập được” không đồng nghĩa với file gốc mà chủ kênh đã upload. Metadata nguồn và biến thể có thể thay đổi.
- Chạy lại bỏ qua file đã thành công và còn đúng dung lượng. Không tính lại SHA-256 của tất cả file cũ mỗi lần chạy. Nếu file bị xóa/thay đổi dung lượng, đưa lại vào hàng đợi.
- Bài ảnh được bỏ qua khi nhận diện được từ metadata; không tải livestream hoặc vượt quyền truy cập video riêng tư.

## File và phiên đăng nhập

Trong thư mục kênh:

- `YYYYMMDD_VIDEOID.mp4` — video; ngày UTC, `19700101` nếu nguồn không cung cấp ngày.
- `.tikbatch.sqlite3` — lịch sử, trạng thái, metadata; không xóa nếu muốn tiếp tục.
- `.mp4.part` và `.mp4.part.json` — dữ liệu tải dở và thông tin tiếp tục.
- `ket-qua.csv` — kết quả, kích thước, độ phân giải, SHA-256 và lỗi.
- `ket-qua.json` — trạng thái cả lượt chạy, lý do dừng và trạng thái quét kênh.

Không tự ghi đè file đích có nội dung khác. Một khóa hệ điều hành ngăn hai tiến trình cùng sửa hàng đợi. Đổi tên tài khoản có thể tạo thư mục mới; bản này chưa tự hợp nhất lịch sử theo ID chủ kênh.

Phiên Chromium và cookie chỉ lưu trên máy ở:

- macOS: `~/Library/Application Support/TikBatch/`
- Windows: `%LOCALAPPDATA%\TikBatch\`

Đóng ứng dụng rồi xóa `browser/` và `cookies.txt` trong thư mục này nếu muốn xóa phiên đăng nhập. Không gửi các file này cho người khác. Ứng dụng không thu mật khẩu và không gửi cookie tới API dịch vụ download bên thứ ba; cookie TikTok được dùng cho yêu cầu tới TikTok. Không có telemetry của TikBatch.

## Kiểm thử và build

```shell
python -m pip install -e ".[dev]"
python -m pytest -q
python build.py
```

PyInstaller cần build trên chính hệ điều hành đích; macOS cần Xcode Command Line Tools cho lipo/codesign. Kết quả ở `dist/`. Script không ký/notarize bản ứng dụng.

`build_portable_mac.py` là phương án macOS không cần Xcode: dùng Python 3.12 từ [python-build-standalone](https://github.com/astral-sh/python-build-standalone), tạo venv từ runtime đó, cài dependencies rồi chạy script. Runtime và các thư viện được sao chép vào bundle cùng giấy phép trong metadata; không kèm Chromium, cookie hay lịch sử tải.

Workflow `.github/workflows/build.yml` tự chạy trên `main` và cung cấp job Windows x64, macOS ARM64 và Intel. Các ZIP được lưu dưới Actions artifacts, không đưa binary, cookie, video hay lịch sử tải vào git.

Xem `BAO-CAO-0.2.md` cho lần cập nhật hiện tại. `BAO-CAO.md` giữ báo cáo lịch sử của bản 0.1.
