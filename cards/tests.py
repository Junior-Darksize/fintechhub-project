import base64
import json
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

def decode_my_secret_data(encrypted_code):
    # DIQQAT: Bu kalit shifrlashda ishlatilgan kalit bilan bir xil bo'lishi shart!
    # Uni o'z loyihangizdagi SECRET_KEY ga almashtiring (16, 24 yoki 32 bayt)
    MY_PRIVATE_KEY = b'bu_juda_maxfiy_16' # Misol uchun 16 baytli kalit

    try:
        # 1. Base64 formatidan baytlarga o'tkazamiz
        raw_data = base64.b64decode(encrypted_code)
        
        # 2. IV (Initialization Vector) - dastlabki 16 bayt
        iv = raw_data[:16]
        
        # 3. Haqiqiy shifrlangan qism - 16-baytdan oxirigacha
        encrypted_payload = raw_data[16:]
        
        # 4. AES obyekti yaratish
        cipher = AES.new(MY_PRIVATE_KEY, AES.MODE_CBC, iv)
        
        # 5. Shifrni ochish va paddingni olib tashlash
        decrypted_bytes = unpad(cipher.decrypt(encrypted_payload), AES.block_size)
        
        # 6. Baytlarni JSON (dict) ko'rinishiga o'tkazish
        return json.loads(decrypted_bytes.decode('utf-8'))

    except ValueError:
        return "Xatolik: Kalit noto'g'ri yoki ma'lumot buzilgan (Padding error)."
    except Exception as e:
        return f"Kutilmagan xatolik: {str(e)}"

# --- ISHLATISH ---
encrypted_code = "cEfGk0BCgDWegtlUI8/F+8h4Q0Wq2Yio0k0hAB2ytW/hV/F2y2o/YWDuuVaQQOz0FWEG7JY8CDrXdgHnGTwikLtSKkS0jnDc/jMBestb4Iqd2FK/RTAj2CA1yA4yLJPEK3stQEi+VK4tR04WdZARywal4+qgz56HIAeVWO0aR9NQR3ujve0CcjLGT1T+7HNnkVhwp2D6QfWuYiPWuNIPLw=="

data = decode_my_secret_data(encrypted_code)
print(data)