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
    if not text:
        return 0
    persian_digits = '۰۱۲۳۴۵۶۷۸۹'
    english_digits = '0123456789'
    translation_table = str.maketrans(persian_digits, english_digits)
    text = text.translate(translation_table)
    nums = re.findall(r'\d+', text)
    return int(''.join(nums)) if nums else 0

def scrape_basalam(url):
    items = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, timeout=60000)
        page.wait_for_load_state("networkidle")
        
        # اسکرول خودکار تا انتهای صفحه
        last_height = page.evaluate("document.body.scrollHeight")
        for _ in range(25):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            new_height = page.evaluate("document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
            
        product_cards = page.query_selector_all('article, a[href*="/product/"]')
        seen_links = set()
        
        for card in product_cards:
            try:
                link_elem = card if card.tag_name == 'a' else card.query_selector('a[href*="/product/"]')
                if not link_elem:
                    continue
                href = link_elem.get_attribute('href')
                if not href or href in seen_links:
                    continue
                
                full_link = href if href.startswith('http') else f"https://basalam.com{href}"
                seen_links.add(href)
                
                card_text = card.inner_text()
                lines = [l.strip() for l in card_text.split('\n') if l.strip()]
                title = lines[0] if lines else "بدون عنوان"
                
                price_per_kg = 0
                for line in lines:
                    if 'کیلویی' in line or 'کیلو' in line:
                        price_per_kg = clean_number(line)
                        break
                if price_per_kg == 0:
                    for line in lines:
                        if 'تومان' in line:
                            price_per_kg = clean_number(line)
                            break
                            
                if price_per_kg > 0:
                    items.append({
                        "title": title,
                        "price_per_kg": price_per_kg,
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
        print("محصولی یافت نشد.")
        return
        
    # مرتب‌سازی بر اساس ارزان‌ترین قیمت کیلویی
    sorted_products = sorted(products, key=lambda x: x['price_per_kg'])
    
    gc = get_gspread_client()
    try:
        sh = gc.open(SHEET_NAME)
        worksheet = sh.sheet1
    except Exception:
        sh = gc.create(SHEET_NAME)
        worksheet = sh.sheet1

    worksheet.clear()
    rows = [["عنوان محصول", "قیمت کیلویی (تومان)", "لینک محصول"]]
    for p in sorted_products:
        rows.append([p['title'], p['price_per_kg'], p['link']])
        
    worksheet.update('A1', rows)
    print("اطلاعات با موفقیت ثبت شد!")

if __name__ == "__main__":
    main()
