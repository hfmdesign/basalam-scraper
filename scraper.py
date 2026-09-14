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
    """استخراج دقیق عدد قیمت فقط از عبارت کیلویی"""
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
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 800})
        page = context.new_page()
        
        print(f"در حال باز کردن لینک: {url}")
        page.goto(url, timeout=90000)
        page.wait_for_load_state("networkidle")
        
        # اسکرول خودکار تا انتهای صفحه برای بارگذاری تمام محصولات
        print("در حال اسکرول و بارگذاری تمام محصولات...")
        last_height = page.evaluate("document.body.scrollHeight")
        
        for _ in range(30):  # اسکرول متوالی برای دریافت کامل لیست
            page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2.5)
            
            new_height = page.evaluate("document.body.scrollHeight")
            if new_height == last_height:
                # حرکت کوچک به بالا و پایین برای تحریک بارگذاری Lazy Loading
                page.evaluate("window.scrollBy(0, -300);")
                time.sleep(1)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
                if page.evaluate("document.body.scrollHeight") == last_height:
                    break
            last_height = new_height

        # یافتن کارت‌های محصولات
        product_cards = page.query_selector_all('article, a[href*="/product/"]')
        seen_links = set()
        
        for card in product_cards:
            try:
                link_elem = card if card.tag_name == 'a' else card.query_selector('a[href*="/product/"]')
                if not link_elem:
                    continue
                
                href = link_elem.get_attribute('href')
                if not href or href in seen_links or '/product/' not in href:
                    continue
                
                full_link = href if href.startswith('http') else f"https://basalam.com{href}"
                
                card_text = card.inner_text()
                price_kg = extract_price_per_kg(card_text)
                
                # فقط مواردی که عبارت کیلویی و عدد معتبر داشتند ذخیره می‌شوند
                if price_kg > 0:
                    seen_links.add(href)
                    lines = [l.strip() for l in card_text.split('\n') if l.strip()]
                    title = lines[0] if lines else "بدون عنوان"
                    
                    items.append({
                        "title": title,
                        "price_per_kg": price_kg,
                        "link": full_link
                    })
            except Exception:
                continue
                
        browser.close()
    return items

def main():
    BASALAM_URL = os.environ.get("BASALAM_URL", "https://basalam.com/s/sunflower-seeds-kernel")
    SHEET_NAME = os.environ.get("GOOGLE_SHEET_NAME", "محصولات باسلام")
    
    products = scrape_basalam(BASALAM_URL)
    
    if not products:
        print("هیچ محصولی با قیمت کیلویی یافت نشد.")
        return
        
    # ۱. مرتب‌سازی بر اساس قیمت کیلویی (از ارزان‌ترین به گران‌ترین)
    sorted_products = sorted(products, key=lambda x: x['price_per_kg'])
    
    # ۲. جدا کردن ۱۰ مورد از ارزان‌ترین‌ها
    top_10_cheapest = sorted_products[:10]
    
    print(f"تعداد کل یافت شده: {len(products)} | ۱۰ مورد ارزان‌تر جدا شد.")
    
    # ارسال به گوگل شیت
    gc = get_gspread_client()
    try:
        sh = gc.open(SHEET_NAME)
        worksheet = sh.sheet1
    except Exception:
        sh = gc.create(SHEET_NAME)
        worksheet = sh.sheet1

    worksheet.clear()
    rows = [["رتبه", "عنوان محصول", "قیمت هر کیلوگرم (تومان)", "لینک مستقیم"]]
    
    for idx, p in enumerate(top_10_cheapest, 1):
        rows.append([idx, p['title'], p['price_per_kg'], p['link']])
        
    worksheet.update('A1', rows)
    print("۱۰ محصول ارزان‌تر با موفقیت در گوگل شیت درج شدند!")

if __name__ == "__main__":
    main()
