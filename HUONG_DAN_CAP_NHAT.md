# 📖 HƯỚNG DẪN QUẢN LÝ VÀ CẬP NHẬT TANKVIDEO STUDIO TỪ A - Z

Tài liệu này hướng dẫn chi tiết quy trình phát hành bản cập nhật mới (dành cho người phát triển/admin) và các cách cập nhật (dành cho người dùng).

---

## 🚀 PHẦN 1: DÀNH CHO BẠN (QUY TRÌNH PHÁT HÀNH PHIÊN BẢN MỚI)

Mỗi khi bạn sửa code, thêm tính năng mới hoặc sửa lỗi và muốn đưa lên cho người dùng, bạn làm theo **5 bước cực kỳ đơn giản** sau:

### 🔹 Bước 1: Tắt TankVideo nếu đang chạy
Trước khi build, hãy chắc chắn bạn đã đóng cửa sổ `TankVideo.exe` (hoặc mở Task Manager kết thúc tiến trình `TankVideo.exe`) để tránh lỗi bị khóa file.

---

### 🔹 Bước 2: Tăng số phiên bản trong mã nguồn
1. Mở file: `app/version.py`
2. Đổi giá trị `APP_VERSION` lên số mới.
   - *Ví dụ:* Đổi từ `"1.1.1"` thành `"1.1.2"`:
     ```python
     APP_VERSION = "1.1.2"
     ```
3. Lưu file lại.

---

### 🔹 Bước 3: Đóng gói lại file `TankVideo.exe` mới
Mở PowerShell hoặc Command Prompt tại thư mục dự án `D:\capcap\CapCap` và chạy lệnh:
```bash
.\.venv\Scripts\pyinstaller.exe CapCap.spec --noconfirm
```
*(Chờ khoảng 1 - 2 phút cho đến khi màn hình báo `Build complete! The results are available in: dist`).*

---

### 🔹 Bước 4: Tạo file bản vá siêu nhẹ `patch.zip` (~32 MB)
Sau khi PyInstaller build xong, chạy script tạo file nén:
```bash
.\.venv\Scripts\python.exe scratch\mk_patch.py
```
👉 Bạn sẽ nhận được file **`dist\patch.zip`** (dung lượng chỉ ~32.3 MB).

---

### 🔹 Bước 5: Đưa lên mạng phát hành cho người dùng

#### 👉 Cách A: Dùng công cụ tự động (Khuyên dùng - 10 giây)
1. Tải file `dist\patch.zip` lên Google Drive của bạn.
2. Nhấp chuột phải vào file trên Drive ➔ Chọn **Chia sẻ (Share)** ➔ Đổi quyền thành **"Bất kỳ ai có đường liên kết" (Anyone with link)** ➔ Bấm **Sao chép đường liên kết**.
3. Chạy file **`publish_update.bat`** ở thư mục gốc:
   - **Phiên bản**: Nhấn `Enter` (nó đã tự nhận phiên bản mới ở Bước 2).
   - **Mô tả**: Nhập nội dung cập nhật (ví dụ: `Sửa lỗi và tối ưu hiệu năng`) rồi nhấn `Enter`.
   - **Link tải**: Dán đường link Google Drive vừa sao chép vào rồi nhấn `Enter`.
4. 🎉 **XONG!** Hệ thống tự động đẩy thông tin lên GitHub Gist. Tất cả người dùng trên toàn bộ các máy khác khi mở app lên sẽ **bị bắt buộc cập nhật ngay lập tức**!

---

#### 👉 Cách B: Cập nhật file `update_tankvideo.bat` (Để gửi cho máy khác chạy file bat)
Nếu bạn muốn gửi file `.bat` cho người khác tự chạy:
1. Lấy mã `FILE_ID` của file `patch.zip` trên Google Drive.  
   *(Ví dụ link: `https://drive.google.com/file/d/1r-asAt_CN35hidm8i1f1xqM-Rn9vBe6S/view` thì `FILE_ID` chính là `1r-asAt_CN35hidm8i1f1xqM-Rn9vBe6S`).*
2. Mở file `tools\update_tankvideo.bat` (hoặc `dist\TankVideo\update_tankvideo.bat`), tìm dòng số 58:
   ```bat
   set "FILE_ID=DÁN_MÃ_FILE_ID_MỚI_VÀO_ĐÂY"
   ```
3. Lưu lại và gửi file `update_tankvideo.bat` này cho các máy khác.

---

## 💻 PHẦN 2: DÀNH CHO NGƯỜI DÙNG (3 CÁCH CẬP NHẬT)

### 🌟 Cách 1: Cập nhật tự động 1-Click trên App (Nhanh nhất - 5 giây)
1. Mở phần mềm TankVideo Studio lên.
2. Nếu có phiên bản mới, màn hình sẽ tự động bật hộp thoại cảnh báo:  
   **"🚨 BẮT BUỘC CẬP NHẬT PHIÊN BẢN MỚI"**.
3. Bấm vào nút **`🚀 CẬP NHẬT NGAY (1-CLICK)`**.
4. Ứng dụng sẽ tự động tải bản vá 32MB về, cài đặt và tự khởi động lại vào phiên bản mới nhất!

---

### 🛠️ Cách 2: Chạy file `update_tankvideo.bat` (Không cần mở app)
1. Tắt phần mềm TankVideo.
2. Vào thư mục phần mềm `TankVideo`, nhấp đúp vào file **`update_tankvideo.bat`**.
3. Cửa sổ dòng lệnh sẽ tự động tải bản cập nhật mới từ Drive về, giải nén và mở lại TankVideo.

---

### 📂 Cách 3: Cập nhật hoàn toàn thủ công bằng tay (Copy - Paste)
Trong trường hợp máy người dùng bị chặn tải hoặc mạng lỗi:
1. Tắt hoàn toàn phần mềm `TankVideo.exe`.
2. Tải file `patch.zip` từ link Google Drive về máy.
3. Giải nén file `patch.zip` ra sẽ được 1 file duy nhất là **`TankVideo.exe`**.
4. Kéo file **`TankVideo.exe`** mới này vào thư mục phần mềm `TankVideo` của máy đó ➔ Chọn **Ghi đè (Replace the file in the destination)**.
5. Mở lại `TankVideo.exe` là đã lên phiên bản mới nhất!

---

## ⚠️ PHẦN 3: CÁC LỖI THƯỜNG GẶP VÀ CÁCH XỬ LÝ

| Hiện tượng | Nguyên nhân | Cách khắc phục |
| :--- | :--- | :--- |
| **Lỗi `Access is denied` khi build PyInstaller** | Do file `TankVideo.exe` vẫn đang chạy ngầm trong máy. | Mở Task Manager tìm `TankVideo.exe` ➔ Bấm **End Task**, sau đó chạy lại lệnh build. |
| **File tải về bị lỗi / File quá nhỏ (< 1MB)** | Do link Google Drive chưa cấp quyền công khai. | Vào Drive ➔ Chuột phải vào file ➔ Chọn **Chia sẻ** ➔ Đổi thành **"Bất kỳ ai có liên kết đều có thể xem"**. |
| **App không hiện thông báo cập nhật** | Do máy tính chưa kết nối Internet hoặc link Gist bị chặn. | Kiểm tra lại kết nối mạng hoặc mở app bấm nút **`🔄 Kiểm tra cập nhật`** trên thanh công cụ. |
