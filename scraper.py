import os
import re
import json
import time
import traceback
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

def extract_price_per_kg_from_text(card_text):
    """استخراج مستقیم عدد دقیق جلوی عبارت کیلویی"""
    text_clean = card_text.translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789'))
    
    match = re.search(r'کیلویی\s*[:|-]?\s*([\d,]+)', text_clean)
    if match:
        num = clean_number(match.group(1))
        if num > 0:
            return num
            
    match2 = re.search(r'([\d,]+)\s*کیلویی', text_clean)
    if match2:
        num = clean_number(match2.group(1))
        if num > 0:
            return num

    lines = card_text.split('\n')
    for line in lines:
        if 'کیلویی' in line:
            num = clean_number(line)
            if num > 0:
                return num

    return "نامشخص"

def scrape_basalam(url):
    items = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        context = browser.new_context(
            viewport={'width': 1440, 'height': 900},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        )
        page = context.new_page()
        
        print(f"در حال باز کردن لینک: {url}")
        # تغییر wait_until به domcontentloaded جهت جلوگیری از Timeout شبکه
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
        time.sleep(5)
        
        print("در حال اسکرول صفحه...")
        for i in range(20):
            page.mouse.wheel(0, 1200)
            time.sleep(1)

        card_elements = page.query_selector_all('a[href*="/product/"]')
        print(f"تعداد کل عناصر لینک یافت شده: {len(card_elements)}")
        
        seen_links = set()
        
        for elem in card_elements:
            try:
                href = elem.get_attribute('href')
                if not href or '/product/' not in href:
                    continue
                
                clean_href = href.split('?')[0]
                if clean_href in seen_links:
                    continue
                
                full_link = clean_href if clean_href.startswith('http') else f"https://basalam.com{clean_href}"
                
                try:
                    parent_card = elem.evaluate_handle('el => el.closest("article") || el.parentElement').as_element()
                    card_text = parent_card.inner_text().strip() if parent_card else elem.inner_text().strip()
                except Exception:
                    card_text = elem.inner_text().strip()
                
                lines = [l.strip() for l in card_text.split('\n') if l.strip()]
                if not lines:
                    continue
                    
                title = lines[0]
                
                prices = [clean_number(l) for l in lines if clean_number(l) >= 1000]
                main_price = prices[0] if prices else 0
                
                price_kg = extract_price_per_kg_from_text(card_text)
                
                seen_links.add(clean_href)
                
                items.append({
                    "title": title,
                    "price": main_price,
                    "price_per_kg": price_kg,
                    "link": full_link,
                    "raw_text": " | ".join(lines)
                })
            except Exception:
                continue
                
        browser.close()
    return items

def main():
    try:
        BASALAM_URL = os.environ.get("BASALAM_URL", "https://basalam.com/s/sunflower-seeds-kernel")
        SHEET_NAME = os.environ.get("GOOGLE_SHEET_NAME", "محصولات باسلام")
        
        products = scrape_basalam(BASALAM_URL)
        
        if not products:
            print("هیچ محصولی پیدا نشد!")
            return
            
        print(f"تعداد کل محصولات استخراج شده: {len(products)}")
        
        gc = get_gspread_client()
        try:
            sh = gc.open(SHEET_NAME)
            worksheet = sh.sheet1
        except Exception:
            sh = gc.create(SHEET_NAME)
            worksheet = sh.sheet1

        worksheet.clear()
        
        rows = [["ردیف", "عنوان محصول", "قیمت اصلی (تومان)", "قیمت کیلویی (تومان)", "لینک مستقیم", "متن کامل کارت"]]
        
        for idx, p in enumerate(products, 1):
            rows.append([idx, p['title'], p['price'], p['price_per_kg'], p['link'], p['raw_text']])
            
        worksheet.update('A1', rows)
        print(f"تعداد {len(products)} محصول با موفقیت در گوگل شیت قرار گرفتند!")
        
    except Exception as e:
        print("خطایی در اجرا رخ داد:")
        traceback.print_exc()
        raise e

if __name__ == "__main__":
    main()
