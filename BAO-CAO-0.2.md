# TikBatch 0.2 — chạy ngầm và xử lý lỗi

Ngày 26/10/2026. Mã nguồn được quản lý tại [lenhatnam79/TikBatch](https://github.com/lenhatnam79/TikBatch).

## Thay đổi

1. Mặc định Chromium chạy headless bằng channel `chromium`. Chỉ mở cửa sổ khi người dùng bấm nút đăng nhập hoặc chủ động bỏ chọn Chạy ngầm. Không tự mở cửa sổ để xử lý lỗi.
2. Dùng một browser context và nhóm tối đa 4 tab chi tiết tái sử dụng. Lỗi khởi chạy được nhớ trong lượt chạy để ngăn thử mở trình duyệt liên tục. Phát hiện yêu cầu đăng nhập/CAPTCHA sẽ giữ hàng đợi và dừng để người dùng xử lý riêng.
3. Khởi đầu tối đa 8 tác vụ video, tăng trần có thể chọn tới 32; tối đa 8 tác vụ lấy nguồn. Mặc định trần 16. Chưa có bằng chứng 32 luôn nhanh hơn 16; bộ điều chỉnh vẫn giảm mức song song khi gặp lỗi mạng hoặc giới hạn truy cập.
4. Lỗi metadata/video không làm giảm toàn bộ số tác vụ tải. Lỗi mạng không ép mở lại trang lấy nguồn; URL hết hạn thử nguồn CDN tương đương rồi lấy nguồn mới ngay trong tác vụ.
5. Giữ nguồn đã ký tới gần thời điểm hết hạn, thay vì bắt buộc làm mới sau 10 phút. Khi không có thời hạn trong URL, cache giới hạn 30 phút.
6. Thử HTML qua request dùng cùng phiên đăng nhập; nếu không đọc được, dùng nhóm tab ngầm. Bổ sung SIGI_STATE, PlayAddrStruct, src/url object và URL bắt đầu bằng `//`.
7. Link DOM/flat không ghi đè metadata đầy đủ; cập nhật được ngày đăng khi API bổ sung dữ liệu. SQLite tự thêm cột phân loại lỗi, giữ lịch sử và video đã thành công.
8. Ghi thêm `ket-qua.json` để biết lỗi quét/lý do dừng ngay cả khi chưa tìm thấy video.
9. Tự kiểm thử/build trên GitHub Actions cho Windows và hai kiến trúc macOS; ZIP giữ cấu trúc app trước khi upload artifact. Kết quả Actions phải được kiểm tra riêng.

## Kiểm thử

54 kiểm thử nội bộ đã qua trên macOS ARM64, gồm 39 ca cũ và 15 ca về headless mặc định, không tự bật cửa sổ, nhóm tab tái sử dụng, bộ nhớ URL có thời hạn, đọc các dạng JSON, phân loại lỗi, làm mới nguồn hết hạn, thử CDN và giữ hàng đợi khi cần đăng nhập.

Ca nhóm tab thực hiện 40 yêu cầu mô phỏng: chỉ tạo 4 tab và 1 context. Ca khởi chạy trình duyệt thất bại thực hiện 8 yêu cầu đồng thời: chỉ gọi khởi chạy một lần và không chuyển sang chế độ hiện cửa sổ. Đây là kiểm thử bằng đối tượng giả; không phải benchmark mạng TikTok.

Kiểm thử hàng đợi 1.000 video vẫn qua; bộ tải ở ca này là bộ tải giả. Ca pipeline 24 file MP4 dùng dữ liệu video thật qua HTTP transport mô phỏng, kiểm tra SHA-256 đúng nguồn. Không được dùng thời gian hai ca này làm dự báo tốc độ tải Internet.

Đã thử khởi chạy Chromium chạy ngầm trên một bản sao tách biệt của phiên ứng dụng; môi trường kiểm thử vẫn trả TargetClosedError. Không sửa hay reset cơ sở dữ liệu tải và phiên trình duyệt đang dùng của người dùng. Chưa xác nhận thực tế mức tăng tốc hoặc tỷ lệ tải thành công của các video trước đó bị lỗi.

## Dùng bản cập nhật

Dừng và đóng 0.1, mở app 0.2, giữ Chạy ngầm bật và chọn lại đúng thư mục cha chứa thư mục kênh. Bắt đầu với trần 16. Các video thành công trước đó được bỏ qua; các mục lỗi được thử lại theo chính sách mới.

Chỉ bấm Mở TikTok / Đăng nhập nếu ứng dụng yêu cầu. Hoàn tất xác minh, đóng cửa sổ rồi tiếp tục. Việc chạy ngầm có thể bị TikTok yêu cầu xác minh; ứng dụng không tự vượt CAPTCHA.

Vẫn chưa nghiệm thu tải hết kênh, chất lượng cao nhất có thể truy cập và logo trong khung hình. Không khẳng định đã sửa hết lỗi nguồn hoặc đạt tốc độ tối đa trước khi có kết quả chạy thực tế.
