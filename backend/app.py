from flask import Flask, request, jsonify
from flask_cors import CORS
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
from bs4 import BeautifulSoup, NavigableString, Tag
import asyncio
import json
import os
import re
from urllib.parse import urljoin, urlparse
import datetime
import traceback 

app = Flask(__name__)
CORS(app)

CONFIG_DIR = "configs"
os.makedirs(CONFIG_DIR, exist_ok=True)

DEBUG_HTML_SAVE_DIR = "debug_channel_html_snapshots"
os.makedirs(DEBUG_HTML_SAVE_DIR, exist_ok=True)


def get_safe_filename(text_input):
    if not text_input: text_input = "untitled"
    try:
        parsed = urlparse(text_input)
        if parsed.scheme and parsed.netloc:
            text_input = parsed.netloc + parsed.path
    except Exception: pass
    safe_name = re.sub(r'[^\w\.-]', '_', text_input)
    safe_name = re.sub(r'_+', '_', safe_name).strip('_.- ')
    return safe_name[:100] 


async def save_debug_html(url, channel_name, html_content, page_title, stage_description=""):
    if not html_content: return
    base_file_name = get_safe_filename(url)
    safe_channel_name = get_safe_filename(channel_name)
    safe_stage_desc = get_safe_filename(stage_description) if stage_description else "content"
    timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    filename = f"{base_file_name}_ch_{safe_channel_name}_stg_{safe_stage_desc}_{timestamp_str}.html"
    filepath = os.path.join(DEBUG_HTML_SAVE_DIR, filename)
    header_comment = (f"<!-- DEBUG: URL:{url} CH:{channel_name} PGTITLE:{page_title} STG:{stage_description} TS:{datetime.datetime.now().isoformat()} FILE:{filename} -->\n\n")
    try:
        with open(filepath, "w", encoding="utf-8") as f: f.write(header_comment + html_content)
       
    except Exception as e: print(f"[DEBUG_SAVE_ERR] {filepath}: {e}")


async def get_page_content_for_all_channels(url):
    all_channel_data = []
    async with async_playwright() as p:
        user_agent_string = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
        browser = await p.chromium.launch(headless=True) 
        context = await browser.new_context(user_agent=user_agent_string, viewport={'width': 1920, 'height': 1080}, java_script_enabled=True, ignore_https_errors=True)
        page = await context.new_page()
        await stealth_async(page)
        processed_channel_identifiers_in_playwright = set()

        try:
            await page.goto(url, timeout=90000, wait_until='domcontentloaded') 
            await page.wait_for_timeout(8000) 
            initial_html_content = await page.content()
            initial_page_title = await page.title()
            await save_debug_html(url, "InitialPageLoad", initial_html_content, initial_page_title, "initial_load_before_interaction")
            for _ in range(2): 
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)"); await page.wait_for_timeout(2500)
            await page.evaluate("window.scrollTo(0, 0)"); await page.wait_for_timeout(1500)

            found_channels_list = []
            isbank_channel_select = await page.query_selector('select#fxRateType')
            
            if isbank_channel_select:
                options_elements = await isbank_channel_select.query_selector_all('option')
                view_button_isbank_selector = 'div.dK_button1[onclick*="CallHandler()"]'
                for option_el in options_elements:
                    opt_value = await option_el.get_attribute("value")
                    opt_text_content = (await option_el.text_content() or "").strip()
                    if not opt_value or not opt_text_content: continue
                    channel_name_isbank = opt_text_content
                    isbank_parsing_context_id = f"isbank_content_for_{opt_value}"
                    unique_id_for_processing = f"isbank_select_{opt_value}"
                    if unique_id_for_processing not in processed_channel_identifiers_in_playwright:
                        found_channels_list.append({
                            "name": channel_name_isbank, "value_for_interaction": opt_value,
                            "active_tab_id_in_html": isbank_parsing_context_id, "is_select_option": True, 
                            "element_handle_for_interaction": isbank_channel_select,
                            "view_button_selector": view_button_isbank_selector,
                            "identifier": unique_id_for_processing, "is_tab": False 
                        })
                        processed_channel_identifiers_in_playwright.add(unique_id_for_processing)
            else:
                tab_selectors_str = 'ul.nav-tabs li a[data-toggle="pill"], [role="tablist"] [role="tab"], a.nav-link[data-bs-toggle="tab"], button.nav-link[data-bs-toggle="tab"]' # افزودن سلکتورهای بیشتر برای تب‌های Bootstrap 5
                tab_elements = await page.query_selector_all(tab_selectors_str)
                for tab_el in tab_elements:
                    try:
                        tab_text = (await tab_el.text_content() or "").strip()
                        if not tab_text or not await tab_el.is_visible(): continue # اگر متنی ندارد یا قابل مشاهده نیست، رد کن

                        tab_pane_id_attr = await tab_el.get_attribute("href") or await tab_el.get_attribute("data-bs-target") or await tab_el.get_attribute("aria-controls") or await tab_el.get_attribute("data-target") # برای آکوردئون‌های قدیمی‌تر

                        if tab_text and tab_pane_id_attr:
                            actual_tab_pane_id = tab_pane_id_attr.lstrip('#')
                            unique_id = f"tab_{get_safe_filename(tab_text)}_{actual_tab_pane_id}"
                            if unique_id not in processed_channel_identifiers_in_playwright:
                                found_channels_list.append({
                                    "name": tab_text, "value_for_interaction": actual_tab_pane_id,
                                    "active_tab_id_in_html": actual_tab_pane_id, 
                                    "is_select_option": False, "element_handle_for_interaction": tab_el,
                                    "view_button_selector": None, "identifier": unique_id, "is_tab": True
                                })
                                processed_channel_identifiers_in_playwright.add(unique_id)
                    except Exception as e_tab_proc: print(f"Error processing tab element: {e_tab_proc}")

            if not found_channels_list:
                found_channels_list = [{"name": "Default Channel", "value_for_interaction": "default",
                                     "active_tab_id_in_html": None, "is_select_option": False, 
                                     "element_handle_for_interaction": None, "view_button_selector": None,
                                     "identifier": "default_single_channel", "is_tab": False}]
            
            print(f"Found {len(found_channels_list)} channels to process for {url}")

            for channel_info_item in found_channels_list:
                ch_name = channel_info_item["name"]
                interaction_val = channel_info_item["value_for_interaction"]
                el_handle = channel_info_item["element_handle_for_interaction"]
                active_tab_id_for_parser = channel_info_item["active_tab_id_in_html"]
                
                if channel_info_item["identifier"] != "default_single_channel":
                    try:
                        if channel_info_item["is_select_option"] and el_handle:
                            await el_handle.select_option(value=interaction_val)
                            await page.wait_for_timeout(2000) 
                            if channel_info_item.get("view_button_selector"):
                                view_btn = await page.query_selector(channel_info_item["view_button_selector"])
                                if view_btn and await view_btn.is_enabled():
                                    await view_btn.click(timeout=7000); await page.wait_for_timeout(6000) 
                        elif el_handle: 
                            await el_handle.click(timeout=7000); await page.wait_for_timeout(5000)
                    except Exception as e_int: print(f"Interaction error ch:'{ch_name}': {e_int}"); continue

                current_content_html = await page.content()
                current_pg_title = await page.title()
                await save_debug_html(url, ch_name, current_content_html, current_pg_title, f"content_after_interaction_with_{get_safe_filename(interaction_val) or 'default'}")
                all_channel_data.append({
                    "channel_name": ch_name, "html_content": current_content_html,
                    "page_title": current_pg_title, "timestamp": datetime.datetime.now().isoformat(),
                    "active_tab_id_in_html": active_tab_id_for_parser 
                })
        except Exception as e_glob: print(f"Global Playwright error: {e_glob}"); traceback.print_exc()
        finally:
            if 'context' in locals() and context: await context.close()
            if 'browser' in locals() and browser: await browser.close()
        return all_channel_data

def parse_selectable_tags(html_content, channel_name, active_tab_id_in_html=None, current_url=None): 
    if not html_content: return {}, []
    soup = BeautifulSoup(html_content, 'html.parser')
    selectable_tags_list = []
    processed_selectors_in_this_channel = set()
    search_context = soup
    
    is_isbank = current_url and "isbank.com.tr" in urlparse(current_url).netloc
    is_borsaistanbul = current_url and "borsaistanbul.com" in urlparse(current_url).netloc
    is_kuveytturk = current_url and "kuveytturk.com.tr" in urlparse(current_url).netloc

    if active_tab_id_in_html and not active_tab_id_in_html.startswith("isbank_content_for_"):
        tab_pane_container = soup.find('div', id=active_tab_id_in_html, class_=lambda x: x and 'tab-pane' in x.split())
        if tab_pane_container: search_context = tab_pane_container
        else: active_fallback = soup.find('div', class_='tab-pane active show'); search_context = active_fallback if active_fallback else soup
    elif is_isbank:
        isbank_table_container = soup.find('div', class_='dk_MC')
        if isbank_table_container: search_context = isbank_table_container
    elif is_kuveytturk and active_tab_id_in_html: # Kuveytturk'te tab ID'si var ama محتوا در همانجا لود نمی‌شود
         tab_pane_container_kt = soup.find('div', id=active_tab_id_in_html, class_=re.compile(r'tab-pane'))
         if tab_pane_container_kt: search_context = tab_pane_container_kt
         else: print(f"[PST_WARN:{channel_name}] KuveytTurk tab pane #{active_tab_id_in_html} not found, using full soup.")

    potential_tables = search_context.find_all('table', recursive=True)
    tables_to_add_final = []
    for table_tag in potential_tables:
        rows_in_table = table_tag.find_all('tr', recursive=False)
        if not rows_in_table and table_tag.find('tbody'): rows_in_table = table_tag.find('tbody').find_all('tr', recursive=False)
        if not rows_in_table or len(rows_in_table) < 1 : continue 
        
        first_valid_row = next((r for r in rows_in_table if r.find(['th', 'td'])), None)
        if not first_valid_row: continue
        cols_count = len(first_valid_row.find_all(['td', 'th'], recursive=False))
        if cols_count < 1 : continue

        relevant_table = False
        if is_isbank: relevant_table = 'dk_MT' in (table_tag.get('class', []))
        elif is_borsaistanbul: relevant_table = table_tag.get('id') and 'indexpage-' in table_tag.get('id')
        elif is_kuveytturk: 
            relevant_table = 'table-portal' in table_tag.get('class', []) and table_tag.find_parent(class_='table-responsive')
        else: relevant_table = not table_tag.find_parent(class_=lambda x: x and 'datetimepicker' in x.split())
        if not relevant_table: continue
        tables_to_add_final.append(table_tag)

    for table_tag in tables_to_add_final:
        tag_id = table_tag.get('id'); classes = table_tag.get('class', [])
        rows = table_tag.find_all('tr'); row_count = len(rows)
        first_row = next((r for r in rows if r.find(['th', 'td'])), None)
        cols_count = len(first_row.find_all(['td', 'th'], recursive=False)) if first_row else 0

        base_sel = f"table#{tag_id}" if tag_id and not tag_id.isnumeric() else \
                   (f"table.{'.'.join(sorted(list(set(c for c in classes if c and c not in ['table', 'table-condensed', 'table-responsive']))[:2]))}" if \
                    [c for c in classes if c and c not in ['table', 'table-condensed', 'table-responsive']] else "table")
        
        final_sel = base_sel
        if active_tab_id_in_html and not active_tab_id_in_html.startswith(("isbank_content_for_", "generated_id_")) and not is_isbank:
            final_sel = f"#{active_tab_id_in_html} {base_sel}"
        elif base_sel == "table": # عمومی‌ترین حالت، سعی در دقیق‌تر کردن
            parent_id_el = table_tag.find_parent(id=re.compile(r'^[a-zA-Z][\w-]*$')) # ID معتبر
            if parent_id_el: final_sel = f"#{parent_id_el.get('id')} table"
        
        text_prev = table_tag.get_text(separator=' ', strip=True)[:50].replace('\n',' ') + "..."
        disp_name = f"T(Sel:{final_sel[:20]}..,R:{row_count}C:{cols_count})P:{text_prev[:15]}"
        unique_key_ch = (final_sel, row_count, cols_count, text_prev[:15])
        if unique_key_ch in processed_selectors_in_this_channel: continue
        processed_selectors_in_this_channel.add(unique_key_ch)
        selectable_tags_list.append({
            "display_name_from_parser": disp_name, "selector": final_sel, "id_attr": tag_id, 
            "class_attr": classes, "text_preview": text_prev, "row_count": row_count, "col_count": cols_count
        })
    return {"channel_name": channel_name}, selectable_tags_list

def parse_rates_from_html(html_content, base_url, page_title_from_playwright, channel_name, selected_selectors):
    market_data_by_selector = {}; parsing_error_messages = []
    if not html_content: return {}, "HTML content None."
    soup = BeautifulSoup(html_content, 'html.parser')
    if "Engellendi" in page_title_from_playwright or "Blocked" in page_title_from_playwright:
        return {}, f"Page blocked (Title: {page_title_from_playwright})."
    if not selected_selectors: return {}, "No selectors."

    for selector_str in selected_selectors:
        elements_found = []; 
        try: elements_found = soup.select(selector_str)
        except Exception as e: msg = f"BS4 sel err '{selector_str}': {e}"; parsing_error_messages.append(msg); market_data_by_selector[selector_str] = []; continue
        if not elements_found: market_data_by_selector[selector_str] = []; continue
            
        data_for_this_selector = []
        for elem_idx, table_el in enumerate(elements_found): 
            if not isinstance(table_el, Tag) or table_el.name != 'table': continue
            
            hdrs = []; hr_el = None; thead = table_el.find('thead'); 
            if thead: hr_el = thead.find('tr')
            if not hr_el:
                cand_trs = table_el.find_all('tr', recursive=False)
                if not cand_trs and table_el.find('tbody'): cand_trs = table_el.find('tbody').find_all('tr', recursive=False)
                for tr in cand_trs: 
                    if tr.find_all('th', recursive=False): hr_el = tr; break
                if not hr_el and cand_trs and cand_trs[0].find_all(['th','td'], recursive=False): hr_el = cand_trs[0]

            if not hr_el: msg = f"No header for '{selector_str}'"; parsing_error_messages.append(msg); continue
            
            h_cells = hr_el.find_all(['th', 'td'], recursive=False)
            for i, cell_h in enumerate(h_cells):
                ht = cell_h.get_text(strip=True)
                hdrs.append(ht if ht else ("item_name" if i == 0 and len(h_cells) > 1 else f"column_{i+1}"))
            
            if not hdrs: msg = f"Empty headers for '{selector_str}'"; parsing_error_messages.append(msg); continue

            data_rows_cont = table_el.find('tbody') or table_el
            for data_row in data_rows_cont.find_all('tr', recursive=False):
                if data_row == hr_el or not data_row.find_all(['td', 'th'], recursive=False): continue
                cells = data_row.find_all(['td', 'th'], recursive=False)
                if len(cells) < 1 : continue
                entry = {}
                for i_c, h_txt in enumerate(hdrs): 
                    val = "N/A"
                    if i_c < len(cells):
                        raw = cells[i_c].get_text(strip=True); val = raw.replace(',', '.')
                        val = re.sub(r'\s+(?:TL|USD|EUR|₺|%)\s*$', '', val, flags=re.I).strip()
                        if not val and raw: val = raw
                    clean_h = re.sub(r'\s+', '_', h_txt.lower()); clean_h = re.sub(r'[^\w_.-]', '', clean_h).strip('_.- '); 
                    entry[clean_h if clean_h else f"col_{i_c+1}"] = val
                if entry: data_for_this_selector.append(entry)
            market_data_by_selector[selector_str] = data_for_this_selector
    return market_data_by_selector, ("; ".join(parsing_error_messages) if parsing_error_messages else None)


@app.route('/render', methods=['POST'])
async def render():
    data = request.get_json(); url = data.get('url'); selected_items = data.get('selected_items', [])
    if not url: return jsonify({"error": "URL is required"}), 400
    
    processed_agg_item_ids = set()
    channel_html_data = await get_page_content_for_all_channels(url)
    res = { "url": url, "aggregated_selectable_items": [], "channels_data_parsed": {}, "channel_specific_info": {}, "global_status_message": None }

    if not channel_html_data: res["global_status_message"] = "No content/channels."; return jsonify({"error": res["global_status_message"], **res}), 500

    user_selected = bool(selected_items)
    for ch_data_item in channel_html_data:
        ch_name_val = ch_data_item.get("channel_name", "Unknown")
        html_val = ch_data_item.get("html_content")
        title_val = ch_data_item.get("page_title", "N/A")
        active_tab_id = ch_data_item.get("active_tab_id_in_html") 

        ch_info = res["channel_specific_info"].get(ch_name_val, {"page_title": title_val, "parsing_error": None})
        ch_info["page_title"] = title_val

        if not html_val:
            err_msg = f"No HTML for '{ch_name_val}'."; ch_info["parsing_error"] = (ch_info["parsing_error"] or "") + err_msg
            res["channel_specific_info"][ch_name_val] = ch_info; continue
        
        _, tags_for_ch = parse_selectable_tags(html_val, ch_name_val, active_tab_id_in_html=active_tab_id, current_url=url)
        
        for tag_detail in tags_for_ch:
            item_id = (ch_name_val, tag_detail.get('selector'))
            if item_id not in processed_agg_item_ids:
                 res["aggregated_selectable_items"].append({
                    "channel_name": ch_name_val,
                    "display_text": f"{ch_name_val}: {tag_detail.get('display_name_from_parser', tag_detail.get('selector'))}", 
                    "actual_selector": tag_detail.get('selector'), "details_from_parser": tag_detail 
                })
                 processed_agg_item_ids.add(item_id)

        if not tags_for_ch and not user_selected: ch_info["parsing_error"] = (ch_info["parsing_error"] or "") + " No selectable tags."

        if user_selected:
            ch_selectors = [item['actual_selector'] for item in selected_items if item.get('channel_name') == ch_name_val and item.get('actual_selector')]
            if ch_selectors:
                rates_map, p_err = parse_rates_from_html(html_val, url, title_val, ch_name_val, ch_selectors)
                if rates_map:
                    if ch_name_val not in res["channels_data_parsed"]: res["channels_data_parsed"][ch_name_val] = {}
                    res["channels_data_parsed"][ch_name_val].update(rates_map)
                if p_err: ch_info["parsing_error"] = (ch_info["parsing_error"] or "") + f" ParseErr: {p_err}"
        res["channel_specific_info"][ch_name_val] = ch_info
    
    if not res["aggregated_selectable_items"] and not user_selected: res["global_status_message"] = "No selectable items found."

    return jsonify(res)

@app.route('/save-data', methods=['POST'])
def save_data():
    data = request.get_json()
    url = data.get('url'); currency_data = data.get('currency_data', {}) 
    if not url or not currency_data: return jsonify({"error": "URL and currency data required"}), 400
    
    sf_name = get_safe_filename(url)
    cf_path = os.path.join(CONFIG_DIR, f"{sf_name}_rates_config.json")
    config = {"url": url, "saved_market_data_by_channel": currency_data}
    try:
        with open(cf_path, 'w', encoding='utf-8') as f: json.dump(config, f, ensure_ascii=False, indent=2)
        return jsonify({"message": "Config saved", "file": cf_path})
    except Exception as e: return jsonify({"error": f"Save failed: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
