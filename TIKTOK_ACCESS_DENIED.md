# Access Denied trong TikBatch 0.2.1

Trang Access Denied thể hiện việc yêu cầu truy cập bị máy chủ từ chối. Điều đó không xác định duy nhất nguyên nhân là thiếu đăng nhập, IP, mạng hay trình duyệt tự động. Chữ `http://` trong nội dung trang lỗi cũng chưa chứng minh thanh địa chỉ/trình duyệt đã chuyển sang HTTP; TikBatch chuẩn hóa link kênh đầu vào về HTTPS.

## Phân biệt và xử lý

1. Kiểm tra cùng link trong Chrome/Safari thông thường trên máy và mạng hiện tại.
2. Nếu trình duyệt thông thường cũng Access Denied, dừng lượt tải và thử lại sau. Chỉ tiếp tục tool khi trang thông thường đã truy cập được. Có thể cung cấp mã Reference cho hỗ trợ TikTok nếu tình trạng kéo dài.
3. Nếu trình duyệt thông thường hoạt động nhưng tool bị từ chối, lưu `ket-qua.json` và mã Reference để phân tích riêng. Điều này chưa chứng minh phiên đăng nhập bị sai.
4. Dùng nút đăng nhập khi ứng dụng nhận diện yêu cầu đăng nhập/CAPTCHA. Không cần xóa phiên, xóa lịch sử tải hay tăng mức song song để xử lý một trang Access Denied.

## Bản 0.2.1 thay đổi gì

- Phân loại riêng `AccessDenied` và `NeedsLogin`.
- Nhận diện HTTP 403, cũng như tài liệu lỗi Access Denied trả về HTTP 200.
- Kiểm tra trang lỗi khi Chromium ném exception trước khi trả về response.
- Dừng điều hướng/lấy nguồn tiếp theo trong cùng lượt chạy sau khi phát hiện từ chối; không tự đổi sang cửa sổ hiển thị hay thử lại từng video tới hết số lần cho phép.
- Giữ các mục chưa hoàn tất trong hàng đợi; ghi `error_code: access_denied` trong `ket-qua.json`.
- Hiển thị thông báo cụ thể khi gặp lỗi ngay trong thao tác Mở TikTok / Đăng nhập, thay vì thay bằng lỗi chung.
- Chỉ lấy mã Reference đã giới hạn ký tự từ trang lỗi; không lưu toàn bộ HTML, URL có tham số hay cookie vào thông báo chẩn đoán.

65 ca kiểm thử nội bộ đã qua, gồm 11 ca bổ sung cho nhận diện từ chối, giữ hàng đợi và thông báo. Các ca mới dùng trang lỗi mô phỏng, không phải bằng chứng truy cập TikTok đã được mở lại. Bản này sửa cách ứng dụng xử lý lỗi; không khẳng định khắc phục được việc truy cập bị máy chủ từ chối.
