import os
import re
import json
import time
from playwright.sync_api import sync_playwright
import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def get_gspread_client():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    if not creds_json:
        raise ValueError("کلید GOOGLE_CREDENTIALS یافت نشد.")
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)

def clean_number(text):
    """تبدیل اعداد فارسی و عربی به انگلیسی و استخراج عدد"""
    if not text:
        return 0
    persian_digits = '۰۱۲۳۴۵۶۷۸۹'
    arabic_digits = '٠١٢٣٤٥٦٧٨٩'
    english_digits = '0123456789'
    
    translation_table = str.maketrans(persian_digits + arabic_digits, english_digits * 2)
    text = text.translate(translation_table)
    nums = re.findall(r'\d+', text)
    return int(''.join(nums)) if nums else 0

def extract_price_per_kg(card_text):
    """استخراج قیمت کیلویی در صورت وجود"""
    lines = [l.strip() for l in card_text.split('\n') if l.strip()]
    for line in lines:
        if 'کیلویی' in line:
            price = clean_number(line)
            if price > 0:
                return price
    return 0

def scrape_basalam(url):
    items = []
    with sync_playwright() as p:
        # تنظیمات مرورگر و User-Agent برای جلوگیری از بلاک شدن
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1440, 'height': 900},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        )
        page = context.new_page()
        
        print(f"در حال باز کردن لینک: {url}")
        page.goto(url, timeout=120000, wait_until="domcontentloaded")
        time.sleep(5)
        
        # اسکرول هوشمند برای بارگذاری تمام محصولات
        print("در حال اسکرول صفحه...")
        for i in range(20):
            page.evaluate("window.scrollBy(0, 1000);")
            time.sleep(1.5)

        # استخراج تمامی لینک‌های محصولات موجود در صفحه
        links = page.query_selector_all('a[href*="/product/"]')
        print(f"تعداد کل عناصر یافت شده: {len(links)}")
        
        seen_links = set()
        
        for link in links:
            try:
                href = link.get_attribute('href')
                if not href or '/product/' not in href:
                    continue
                
                # یکسان‌سازی آدرس لینک
                clean_href = href.split('?')[0]
                if clean_href in seen_links:
                    continue
                
                full_link = clean_href if clean_href.startswith('http') else f"https://basalam.com{clean_href}"
                card_text = link.inner_text().strip()
                
                if not card_text:
                    # تلاش برای دریافت متن از عنصر والد در صورت خالی بودن متن لینک
                    parent = link.query_selector('xpath=..')
                    if parent:
                        card_text = parent.inner_text().strip()
                
                lines = [l.strip() for l in card_text.split('\n') if l.strip()]
                title = lines[0] if lines else "بدون عنوان"
                
                # استخراج تمام اعداد مربوط به قیمت موجود در متن کارت
                prices = [clean_number(l) for l in lines if clean_number(l) > 1000]
                main_price = prices[0] if prices else 0
                price_kg = extract_price_per_kg(card_text)
                
                seen_links.add(clean_href)
                
                items.append({
                    "title": title,
                    "price": main_price,
                    "price_per_kg": price_kg if price_kg > 0 else "نامشخص",
                    "link": full_link,
                    "raw_text": " | ".join(lines[:4])  # خلاصه اطلاعات کارت
                })
            except Exception as e:
                continue
                
        browser.close()
    return items

def main():
    BASALAM_URL = os.environ.get("BASALAM_URL", "https://basalam.com/s/sunflower-seeds-kernel")
    SHEET_NAME = os.environ.get("GOOGLE_SHEET_NAME", "محصولات باسلام")
    
    products = scrape_basalam(BASALAM_URL)
    
    if not products:
        print("هیچ محصولی پیدا نشد! لطفا بررسی کنید که لینک ورودی درست باشد.")
        return
        
    print(f"تعداد کل محصولات استخراج شده: {len(products)}")
    
    # اتصال به گوگل شیت
    gc = get_gspread_client()
    try:
        sh = gc.open(SHEET_NAME)
        worksheet = sh.sheet1
    except Exception:
        sh = gc.create(SHEET_NAME)
        worksheet = sh.sheet1

    worksheet.clear()
    
    # ساخت ردیف‌های عنوان و دیتای کامل
    rows = [["ردیف", "عنوان محصول", "قیمت اصلی (تومان)", "قیمت کیلویی (تومان)", "لینک مستقیم", "خلاصه کارت"]]
    
    for idx, p in enumerate(products, 1):
        rows.append([idx, p['title'], p['price'], p['price_per_kg'], p['link'], p['raw_text']])
        
    worksheet.update('A1', rows)
    print(f"تمام {len(products)} محصول با موفقیت در گوگل شیت ثبت شدند!")

if __name__ == "__main__":
    main()
