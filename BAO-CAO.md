# Báo cáo bàn giao TikBatch 0.1

Ngày: 26/10/2026 · Trạng thái: **bản thử nghiệm; chưa nghiệm thu tải toàn kênh TikTok thực tế**.

## Kết quả bàn giao

- Mã nguồn Python, giao diện desktop tiếng Việt dùng chung cho Windows/macOS.
- Bản ứng dụng macOS Apple Silicon kèm runtime Python và các thư viện; không cần cài Python riêng, Chromium cài riêng bằng nút trong ứng dụng.
- Script khởi chạy mã nguồn trên Windows/macOS, script PyInstaller và workflow build ba kiến trúc. Chưa có `.exe` Windows được build, chưa chạy kiểm thử Windows/Intel và chưa đưa dự án lên dịch vụ bên ngoài.
- Ảnh giao diện được chụp từ ứng dụng chạy thực sự bằng chế độ offscreen, không phải ảnh thiết kế giả.
- Không tích hợp API trả phí, không có máy chủ nhận cookie của TikBatch.

## Chức năng đã viết

Nhập link kênh và chọn thư mục; vừa quét vừa xử lý hàng đợi; lưu trạng thái trong SQLite; lọc trùng ID; tải song song khởi đầu tối đa 4 và tự điều chỉnh đến mức trần do người dùng chọn (1–16); giới hạn riêng việc lấy nguồn; tải streaming xuống ổ đĩa; tiếp tục file dở bằng Range/If-Range khi có thể; làm mới nguồn ở lần thử lại; chờ Retry-After khi bị giới hạn; tối đa 4 lần thử/video/lượt; dừng và tiếp tục; kiểm tra dung lượng; xuất CSV.

Ưu tiên nguồn MP4 playback có âm thanh, không dùng downloadAddr hoặc nguồn bị đánh dấu watermark. Không chuyển mã. Kiểm tra container, luồng hình/âm thanh, giải mã khung hình đầu và SHA-256. Không có thuật toán phát hiện logo theo hình ảnh hoặc xác nhận file upload nguyên gốc của chủ kênh.

Trình duyệt dùng profile riêng và lưu phiên cục bộ. Thử trực tiếp trước; khi cần, mở cửa sổ TikTok để người dùng tự xác minh/đăng nhập. Không tự giải CAPTCHA. Quét lỗi được ghi là chưa hoàn tất, dù các video đã tìm thấy vẫn có thể tải.

## Kết quả kiểm thử nội bộ

Lệnh: `python -m pytest tests -q --durations=5` trên Python 3.12.15, macOS ARM64, Qt offscreen.

**39 ca qua, 0 ca thất bại, thời gian toàn bộ khoảng 7,10 giây ở lần chạy ghi nhận.**

| Nhóm | Kết quả và ý nghĩa |
|---|---|
| Hàng đợi mô phỏng 1.000 video | Xử lý đủ, không trùng; lần chạy lại không gọi tải thêm. Khoảng 0,71 giây, chỉ là kiểm tra điều phối và SQLite với bộ tải giả, không phải tốc độ TikTok. |
| Luồng tải 24 file MP4 mẫu | Dùng HTTP transport mô phỏng và file MP4 thật có hình/âm thanh; tất cả được kiểm tra và SHA-256 trùng nguồn. Khoảng 0,21 giây, không bao gồm Internet. |
| Tiếp tục tải dở | Kiểm tra Range/If-Range, máy chủ bỏ qua Range, Content-Range sai và validator đổi; không ghép nhầm dữ liệu. |
| Nguồn lỗi | 429/503 và Retry-After; HTML thay video; dữ liệu hỏng hoặc thiếu byte; không chốt thành MP4 thành công. |
| Lưu tiến độ | Khôi phục job đang chạy, chống trùng, xử lý file bị xóa/đổi dung lượng, dừng an toàn và giữ hàng chờ. |
| Dữ liệu người dùng | Không ghi đè file đích khác nội dung; khóa chống hai tiến trình dùng cùng hàng đợi; dừng trước request khi thiếu dung lượng. |
| Lựa chọn chất lượng | Loại watermark/download, video-only, bytevc2 và giao thức chưa hỗ trợ; chọn biến thể theo độ phân giải/bitrate. |
| Giao diện | Khởi tạo cửa sổ, khóa/mở nút khi đang chạy, hiển thị quét chưa hoàn tất và tiến độ dừng đúng tỷ lệ. |

Kiểm tra riêng bản ứng dụng portable: chạy entry point trong bundle, mở và chụp được giao diện; kiểm tra các import Qt/HTTPX/yt-dlp/PyAV/Playwright từ runtime đi kèm. Không coi kiểm tra offscreen là nghiệm thu tương tác đầy đủ.

## Thử nghiệm trên kênh mẫu

Kênh: `https://www.tiktok.com/@hong_le_`.

| Thử nghiệm | Kết quả |
|---|---|
| HTTP trực tiếp tới hồ sơ | HTTP 200 nhưng nội dung khoảng 1.462 byte là trang kiểm tra, không có dữ liệu hồ sơ cần thiết. HTTP 200 không được coi là quét thành công. |
| yt-dlp 2026.10.21 | Không lấy được secondary user ID; chưa liệt kê được video. |
| Trang embed của kênh | Đọc được 13 mục metadata trong lần thử; trường playAddr trống. Đây là tập con từ embed, không chứng minh tổng số video và không đủ để tải video. |
| Chromium qua Playwright | Đã tải được Chromium, nhưng cả thử headless và có cửa sổ đều lỗi TargetClosedError; log headless ghi tiến trình thoát SIGTRAP. Chưa xác định nguyên nhân và chưa kiểm chứng được trang kênh trong trình duyệt này. |
| Chạy CLI thật của TikBatch | Kết thúc có kiểm soát với scan=incomplete, 0 video tải thành công, xuất CSV; mã thoát 1. Không báo thành công giả. |

**Chưa tải thành công video thật nào của kênh mẫu trong môi trường này.** Vì vậy chưa có bằng chứng nghiệm thu chất lượng cao nhất, không logo, độ đầy đủ của danh sách hoặc tốc độ tải hàng nghìn video. Chưa thể đưa ra thời gian tải dự kiến có cơ sở.

## Giới hạn cần biết

- Windows và macOS Intel mới được chuẩn bị mã nguồn/quy trình build, chưa chạy trên máy đích.
- macOS portable chưa ký Developer ID/notarize. Build PyInstaller trên máy hiện tại bị thiếu Xcode Command Line Tools; đã thay bằng bundle Python portable và kiểm tra khởi tạo giao diện.
- Có thể phải đăng nhập hoặc xác minh trực tiếp trong cửa sổ TikTok. Phần trình duyệt vẫn cần thử thực tế trên máy sử dụng và sửa nếu TikTok trả schema khác.
- Dừng giữa lúc quét sẽ quét lại danh sách từ đầu ở lượt sau; video đã lưu vẫn được bỏ qua. Chưa lưu con trỏ phân trang để nối tiếp phần quét.
- Tên tài khoản thay đổi có thể tạo thư mục mới; chưa hợp nhất theo ID chủ kênh.
- Chưa có benchmark mạng thật hoặc cam kết “nhanh nhất”. Thuật toán điều chỉnh song song là điểm khởi đầu cần đo trên TikTok thực tế.
- Không giải mã toàn bộ file khi xác minh, không tự kiểm tra logo trong từng khung hình và không tính lại hash của tất cả file cũ mỗi lần chạy.

## Bước nghiệm thu tiếp theo

1. Mở app trên macOS ngoài môi trường kiểm thử, cài Chromium bằng nút trong app.
2. Mở TikTok/đăng nhập nếu cần, xác nhận kênh mẫu xem được bình thường.
3. Chạy một lượt ngắn, kiểm tra video có âm thanh, không logo TikTok chèn và đối chiếu độ phân giải/chất lượng với nguồn.
4. Nếu lấy được nguồn ổn định, đo các mức song song 2/4/8/16 trên cùng tập video để chỉnh thuật toán; kiểm tra kênh lớn và tình trạng quét tới cuối nguồn.
5. Build và chạy smoke test trên Windows thật trước khi phát hành `.exe`.

Các bước này là công việc còn lại để nghiệm thu, không được tính là đã hoàn thành trong lần bàn giao này. Xem README để chạy ứng dụng và vị trí nhật ký/CSV.
