import tkinter as tk
from tkinter import ttk, messagebox
import requests
from bs4 import BeautifulSoup
import pandas as pd
import os
import json
import threading
import time
from urllib.parse import urljoin
from queue import Queue, Empty
from PIL import Image, ImageTk


# Funkcja do dynamicznego wyszukiwania pliku z ikoną
def find_logo():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(current_dir, 'logo_high_res_1.ico')  # Plik .ico
    if os.path.exists(icon_path):
        return icon_path
    else:
        return None


CONFIG_FILE = os.path.join(os.getcwd(), "config.json")
EXCEL_FILE = os.path.join(os.getcwd(), "wszystkie_przetargi.xlsx")  # Plik do przechowywania wszystkich przetargów


class SearchWorker(threading.Thread):
    def __init__(self, sites, selectors, keywords, log_callback, result_callback, interval, all_results_callback,
                 unfiltered_callback, progress_bar):
        super().__init__()
        self.sites = sites
        self.selectors = selectors
        self.keywords = keywords
        self.log_callback = log_callback
        self.result_callback = result_callback
        self.interval = interval
        self.all_results_callback = all_results_callback  # Callback do zapisywania wszystkich przetargów
        self.unfiltered_callback = unfiltered_callback  # Callback do zapisywania niespełniających kryteriów
        self.stop_event = threading.Event()
        self.progress_bar = progress_bar  # Pasek ładowania

    def run(self):
        total_steps = 100  # Pasek postępu ma 100 kroków
        step_duration = self.interval / total_steps  # Czas trwania jednego kroku

        while not self.stop_event.is_set():
            self.perform_search()

            # Resetujemy pasek postępu
            self.progress_bar['value'] = 0
            self.log_callback(f"Przerwa {self.interval} sekund przed kolejnym wyszukiwaniem...")

            for i in range(total_steps):
                if self.stop_event.is_set():
                    return
                time.sleep(step_duration)  # Czekamy odpowiednią liczbę sekund
                self.progress_bar.after(0, self.progress_bar.step, 1)  # Zlecamy aktualizację paska w głównym wątku

    def perform_search(self):
        self.log_callback(f"Rozpoczynam przeszukiwanie stron: {self.sites}")
        for site, selector_list in zip(self.sites, self.selectors):
            self.log_callback(f"Przeszukuję stronę: {site}")
            for selector in selector_list:
                self.log_callback(f"Używam selektora: {selector}")
                try:
                    response = requests.get(site, timeout=10)
                    self.log_callback(f"Otrzymano odpowiedź od strony: {site} - Status kodu: {response.status_code}")
                except requests.exceptions.RequestException as e:
                    self.log_callback(f"Błąd podczas pobierania strony: {site}\nSzczegóły: {e}")
                    continue

                soup = BeautifulSoup(response.content, 'html.parser')
                tenders = soup.select(selector)[:20]
                self.log_callback(f"Znaleziono {len(tenders)} przetargów na stronie: {site}")

                for tender in tenders:
                    title = tender.get_text(strip=True)
                    link = tender.get('href')
                    if not link:
                        self.log_callback(f"Pominięto przetarg bez linku: {title}")
                        continue
                    link = urljoin(site, link)

                    # Logowanie zapisywania wszystkich przetargów
                    self.log_callback(f"Zapisuję wszystkie przetargi: Tytuł: {title}, Link: {link}")
                    self.all_results_callback(title, link)

                    found_keyword = False
                    # Logowanie sprawdzania słów kluczowych
                    for keyword in self.keywords:
                        self.log_callback(f"Sprawdzam słowo kluczowe '{keyword}' w tytule przetargu: {title}")
                        if keyword.lower() in title.lower():
                            self.log_callback(f"Znaleziono dopasowanie słowa kluczowego '{keyword}' w tytule: {title}")
                            self.result_callback(title, link, keyword)
                            found_keyword = True
                            break

                    if not found_keyword:
                        self.log_callback(f"Brak dopasowania dla tytułu: {title}")
                        self.unfiltered_callback(title, link)

    def stop(self):
        self.log_callback("Zatrzymywanie wyszukiwania...")
        self.stop_event.set()

class MainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Przeszukiwarka Przetargów")
        self.geometry("800x600")

        # Ustawienie ikony aplikacji
        icon_path = find_logo()
        if icon_path:
            try:
                self.iconbitmap(icon_path)  # Używamy pliku .ico
            except Exception as e:
                print(f"Błąd podczas ustawiania ikony: {e}")
        else:
            print("Ikona aplikacji nie została znaleziona.")

        # Inicjalizacja kolejki logów
        self.log_queue = Queue()

        self.data_memory = set()  # Pamięć dla wyników dopasowanych do słów kluczowych
        self.all_data_memory = set()  # Pamięć dla wszystkich wyników, aby uniknąć duplikatów
        self.config_data = self.load_config()
        self.search_thread = None

        self.create_widgets()
        self.load_data_from_config()

        # Sprawdzanie kolejki co 100 ms
        self.after(100, self.check_log_queue)

    def create_widgets(self):
        self.tabControl = ttk.Notebook(self)

        # Zakładka stron
        self.sites_frame = ttk.Frame(self.tabControl)
        self.tabControl.add(self.sites_frame, text="Strony")

        # Pasek postępu
        self.progress_bar = ttk.Progressbar(self.sites_frame, orient='horizontal', mode='determinate', length=400)
        self.progress_bar.pack(pady=10)

        # Nagłówek dla stron internetowych
        site_label = tk.Label(self.sites_frame, text="Dodaj nową stronę internetową", font=("Arial", 12, "bold"))
        site_label.pack(pady=(10, 2))

        # Pole do wpisywania adresu strony internetowej
        self.site_entry = tk.Entry(self.sites_frame)
        self.site_entry.pack(pady=(0, 5), fill=tk.X, expand=True)
        self.site_entry.config(width=int(self.winfo_width() * 0.9))

        # Przycisk dodawania strony i usuwania stron
        button_frame = tk.Frame(self.sites_frame)
        button_frame.pack(pady=(0, 10))
        add_button = tk.Button(button_frame, text="Dodaj stronę", command=self.add_site)
        add_button.pack(side=tk.LEFT, padx=(0, 10))
        remove_button = tk.Button(button_frame, text="Usuń stronę", command=self.remove_site)
        remove_button.pack(side=tk.LEFT)

        # Lista stron internetowych
        self.sites_listbox = tk.Listbox(self.sites_frame)
        self.sites_listbox.pack(padx=10, pady=(5, 10), fill=tk.BOTH, expand=True)

        # Przycisk start
        start_button = tk.Button(self.sites_frame, text="Rozpocznij wyszukiwanie", command=self.start_search)
        start_button.place(relx=1.0, y=10, anchor="ne")

        stop_button = tk.Button(self.sites_frame, text="Zatrzymaj wyszukiwanie", command=self.stop_search)
        stop_button.place(relx=1.0, y=50, anchor="ne")

        # Zakładka ustawień
        self.settings_frame = ttk.Frame(self.tabControl)
        self.tabControl.add(self.settings_frame, text="Ustawienia")

        tk.Label(self.settings_frame, text="Czas pętli (sekundy)").pack(pady=5)
        self.loop_time_entry = tk.Entry(self.settings_frame)
        self.loop_time_entry.pack(pady=5)

        accept_time_button = tk.Button(self.settings_frame, text="Akceptuj", command=self.accept_time_interval)
        accept_time_button.pack(pady=5)

        tk.Label(self.settings_frame, text="Dodaj słowo kluczowe").pack(pady=5)
        self.keyword_entry = tk.Entry(self.settings_frame)
        self.keyword_entry.pack(pady=5)

        add_keyword_button = tk.Button(self.settings_frame, text="Dodaj słowo kluczowe", command=self.add_keyword)
        add_keyword_button.pack(pady=5)

        remove_keyword_button = tk.Button(self.settings_frame, text="Usuń słowo kluczowe", command=self.remove_keyword)
        remove_keyword_button.pack(pady=5)

        self.keywords_listbox = tk.Listbox(self.settings_frame)
        self.keywords_listbox.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        # Zakładka selektorów
        self.selectors_frame = ttk.Frame(self.tabControl)
        self.tabControl.add(self.selectors_frame, text="Selektory")

        # Nagłówek dla selektorów
        selector_label = tk.Label(self.selectors_frame, text="Dodaj nowy selektor CSS", font=("Arial", 12, "bold"))
        selector_label.pack(pady=(20, 5))

        # Pole do wpisywania selektora
        self.selector_entry = tk.Entry(self.selectors_frame)
        self.selector_entry.pack(pady=5, fill=tk.X, expand=True)
        self.selector_entry.config(width=int(self.winfo_width() * 0.9))

        # Przycisk dodawania selektora i usuwania selektorów
        button_selector_frame = tk.Frame(self.selectors_frame)
        button_selector_frame.pack(pady=(10, 10))
        add_selector_button = tk.Button(button_selector_frame, text="Dodaj selektor", command=self.add_selector)
        add_selector_button.pack(side=tk.LEFT, padx=(0, 10))
        remove_selector_button = tk.Button(button_selector_frame, text="Usuń selektor", command=self.remove_selector)
        remove_selector_button.pack(side=tk.LEFT)

        self.selectors_tree = ttk.Treeview(self.selectors_frame, columns=("Strona", "Selektory"), show="headings")
        self.selectors_tree.heading("Strona", text="Strona")
        self.selectors_tree.heading("Selektory", text="Selektory (przecinek oraz spacja po selektorze) mozna dodac kilka selektorów dla jednej strony")
        self.selectors_tree.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        # Zakładka wyników
        self.results_frame = ttk.Frame(self.tabControl)
        self.tabControl.add(self.results_frame, text="Wyniki")

        self.results_tree = ttk.Treeview(self.results_frame, columns=("Tytuł", "Link", "Słowo kluczowe"),
                                         show="headings")
        self.results_tree.heading("Tytuł", text="Tytuł")
        self.results_tree.heading("Link", text="Link")
        self.results_tree.heading("Słowo kluczowe", text="Słowo kluczowe")
        self.results_tree.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        # Zakładka pomoc
        self.help_frame = ttk.Frame(self.tabControl)
        self.tabControl.add(self.help_frame, text="Pomoc")

        help_text = """
    Jak zdobyć selektor CSS ze strony internetowej?

    1. Otwórz stronę internetową w przeglądarce (np. Chrome lub Firefox).
    2. Kliknij prawym przyciskiem myszy na elemencie, który chcesz zbadać (np. tytuł przetargu) i wybierz "Zbadaj" lub "Inspect".
    3. Otworzy się narzędzie developerskie, w którym znajdziesz podświetlony kod HTML odpowiadający temu elementowi.
    4. Kliknij prawym przyciskiem myszy na podświetlonym kodzie HTML i wybierz "Copy" > "Copy selector" (Kopiuj selektor).
    5. Skopiowany selektor wklej w aplikacji w zakładce "Selektory", aby móc go wykorzystać do wyszukiwania elementów na stronie.

    Przykład selektora CSS:
    - div.article > h1.title
    - #main-content > div > p
    """
        help_label = tk.Label(self.help_frame, text=help_text, justify="left")
        help_label.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        self.tabControl.pack(expand=1, fill="both")

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                self.log_message("Błąd podczas wczytywania pliku konfiguracyjnego.")
                return {"urls": [], "keywords": [], "loop_time": 30}
        return {"urls": [], "keywords": [], "loop_time": 30}

    def save_config(self):
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(self.config_data, f, indent=4)
            self.log_message("Plik konfiguracyjny został zapisany.")
        except IOError as e:
            self.log_message(f"Błąd podczas zapisywania pliku konfiguracyjnego: {e}")

    def load_data_from_config(self):
        for site_data in self.config_data["urls"]:
            url = site_data["url"]
            selectors = ", ".join(site_data["selectors"])
            self.sites_listbox.insert(tk.END, url)
            self.selectors_tree.insert("", "end", values=(url, selectors))
        self.log_message("Wczytano konfigurację stron i selektorów.")

        for keyword in self.config_data["keywords"]:
            self.keywords_listbox.insert(tk.END, keyword)
        self.log_message("Wczytano słowa kluczowe.")

        self.loop_time_entry.insert(0, str(self.config_data.get("loop_time", 30)))
        self.log_message(f"Ustawiono czas pętli na {self.config_data.get('loop_time', 30)} sekund.")

    def add_site(self):
        url = self.site_entry.get()
        if self.is_valid_url(url):
            if url in self.sites_listbox.get(0, tk.END):
                messagebox.showerror("Błąd", "Ta strona jest już dodana.")
                self.log_message(f"Strona {url} jest już na liście.")
            else:
                self.sites_listbox.insert(tk.END, url)
                self.config_data["urls"].append({"url": url, "selectors": []})
                self.save_config()
                self.site_entry.delete(0, tk.END)
                self.refresh_selectors_tree()  # Odśwież selektory po dodaniu strony
                self.log_message(f"Dodano nową stronę: {url}")
        else:
            messagebox.showerror("Błędny URL", "Wprowadź poprawny adres URL.")
            self.log_message(f"Podano nieprawidłowy URL: {url}")

    def remove_site(self):
        selected = self.sites_listbox.curselection()
        if selected:
            url = self.sites_listbox.get(selected[0])
            self.sites_listbox.delete(selected[0])
            self.config_data["urls"] = [site for site in self.config_data["urls"] if site["url"] != url]
            self.save_config()
            self.refresh_selectors_tree()  # Odśwież selektory po usunięciu strony
            self.log_message(f"Usunięto stronę: {url}")

    def add_selector(self):
        selected = self.selectors_tree.focus()
        if selected:
            url = self.selectors_tree.item(selected)["values"][0]
            selector = self.selector_entry.get()
            if selector:
                for site in self.config_data["urls"]:
                    if site["url"] == url:
                        site["selectors"].append(selector)
                        self.save_config()
                        self.refresh_selectors_tree()
                        self.selector_entry.delete(0, tk.END)
                        self.log_message(f"Dodano selektor: {selector} dla strony: {url}")
                        return
            else:
                messagebox.showerror("Błąd", "Wprowadź selektor przed dodaniem.")
                self.log_message("Nie wprowadzono selektora.")
        else:
            messagebox.showerror("Błąd", "Wybierz stronę przed dodaniem selektora.")
            self.log_message("Nie wybrano strony.")

    def remove_selector(self):
        selected = self.selectors_tree.focus()
        if selected:
            url, selectors = self.selectors_tree.item(selected)["values"]
            selectors_list = selectors.split(", ")
            if selectors_list:
                selector_to_remove = self.selector_entry.get()
                if selector_to_remove in selectors_list:
                    selectors_list.remove(selector_to_remove)
                    for site in self.config_data["urls"]:
                        if site["url"] == url:
                            site["selectors"] = selectors_list
                            self.save_config()
                            self.refresh_selectors_tree()
                            self.log_message(f"Usunięto selektor: {selector_to_remove} dla strony: {url}")
                            return
                else:
                    messagebox.showerror("Błąd", "Selekcja nie istnieje.")
                    self.log_message("Selekcja nie istnieje.")
            else:
                messagebox.showerror("Błąd", "Brak selektorów do usunięcia.")
                self.log_message("Brak selektorów do usunięcia.")
        else:
            messagebox.showerror("Błąd", "Wybierz selektor do usunięcia.")
            self.log_message("Nie wybrano selektora do usunięcia.")

    def refresh_selectors_tree(self):
        for item in self.selectors_tree.get_children():
            self.selectors_tree.delete(item)
        for site_data in self.config_data["urls"]:
            url = site_data["url"]
            selectors = ", ".join(site_data["selectors"])
            self.selectors_tree.insert("", "end", values=(url, selectors))
        self.log_message("Odświeżono widok selektorów.")

    def add_keyword(self):
        keyword = self.keyword_entry.get()
        if keyword:
            self.keywords_listbox.insert(tk.END, keyword)
            self.config_data["keywords"].append(keyword)
            self.save_config()
            self.keyword_entry.delete(0, tk.END)
            self.log_message(f"Dodano nowe słowo kluczowe: {keyword}")
        else:
            messagebox.showerror("Błąd", "Wprowadź słowo kluczowe.")
            self.log_message("Nie wprowadzono słowa kluczowego.")

    def remove_keyword(self):
        selected = self.keywords_listbox.curselection()
        if selected:
            keyword = self.keywords_listbox.get(selected[0])
            self.keywords_listbox.delete(selected[0])
            self.config_data["keywords"] = [kw for kw in self.config_data["keywords"] if kw != keyword]
            self.save_config()
            self.log_message(f"Usunięto słowo kluczowe: {keyword}")
        else:
            messagebox.showerror("Błąd", "Wybierz słowo kluczowe do usunięcia.")
            self.log_message("Nie wybrano słowa kluczowego do usunięcia.")

    def accept_time_interval(self):
        try:
            loop_time = int(self.loop_time_entry.get())
            self.config_data["loop_time"] = loop_time
            self.save_config()
            messagebox.showinfo("Sukces", f"Czas pętli został ustawiony na {loop_time} sekund.")
            self.log_message(f"Ustawiono czas pętli na {loop_time} sekund.")
        except ValueError:
            messagebox.showerror("Błąd", "Wprowadź poprawny czas pętli w sekundach.")
            self.log_message("Nieprawidłowa wartość dla czasu pętli.")

    def start_search(self):
        if self.search_thread is not None and self.search_thread.is_alive():
            messagebox.showerror("Błąd", "Wyszukiwanie jest już w toku.")
            self.log_message("Wyszukiwanie już działa.")
            return

        try:
            loop_time = int(self.loop_time_entry.get())
        except ValueError:
            messagebox.showerror("Błąd", "Wprowadź poprawny czas pętli w sekundach.")
            self.log_message("Nieprawidłowa wartość czasu pętli.")
            return

        if not self.keywords_listbox.size():
            messagebox.showerror("Błąd", "Dodaj przynajmniej jedno słowo kluczowe.")
            self.log_message("Brak słów kluczowych.")
            return

        if not self.selectors_tree.get_children():
            messagebox.showerror("Błąd", "Dodaj przynajmniej jeden selektor.")
            self.log_message("Brak selektorów.")
            return

        self.config_data["loop_time"] = loop_time
        self.save_config()

        sites = [self.sites_listbox.get(i) for i in range(self.sites_listbox.size())]
        selectors = [self.selectors_tree.item(item, "values")[1].split(", ") for item in
                     self.selectors_tree.get_children()]
        keywords = [self.keywords_listbox.get(i) for i in range(self.keywords_listbox.size())]

        self.log_message(
            f"Rozpoczynam wyszukiwanie: strony={sites}, selektory={selectors}, słowa kluczowe={keywords}, czas pętli={loop_time} sekund")

        self.search_thread = SearchWorker(sites, selectors, keywords, self.log_message, self.handle_new_tender,
                                          loop_time, self.handle_all_results, self.handle_unfiltered_tender,
                                          self.progress_bar)
        self.search_thread.start()

    def stop_search(self):
        if self.search_thread is not None:
            self.search_thread.stop()
            self.log_message("Wyszukiwanie zostało zatrzymane.")
            messagebox.showinfo("Sukces", "Wyszukiwanie zostało zatrzymane.")

    def handle_new_tender(self, title, link, keyword):
        if title not in self.data_memory:
            self.data_memory.add(title)
            self.save_filtered_tender(title, link)  # Zapisujemy do pliku przetargi spełniające kryteria
            self.after(0, lambda: self.add_result_to_view(title, link, keyword))  # Użycie after
            self.log_message(f"Znaleziono przetarg: Tytuł: {title}, Link: {link}, Słowo kluczowe: {keyword}")

    def save_unfiltered_tender(self, title, link):
        data = {'Tytuł': [title], 'Link': [link]}
        df_new = pd.DataFrame(data)
        try:
            if os.path.exists("unfiltered_przetargi.xlsx"):
                df_existing = pd.read_excel("unfiltered_przetargi.xlsx")

                # Sprawdzenie, czy link już istnieje
                if link in df_existing['Link'].values:
                    self.log_message(f"Link już istnieje w pliku: {link}")
                    return

                # Połączenie istniejących danych z nowymi
                df_combined = pd.concat([df_existing, df_new], ignore_index=True)
                df_combined.to_excel("unfiltered_przetargi.xlsx", index=False)
            else:
                df_new.to_excel("unfiltered_przetargi.xlsx", index=False)
            self.log_message(f"Zapisano przetarg niespełniający kryteriów: {title}")
        except Exception as e:
            self.log_message(f"Błąd podczas zapisu przetargu niespełniającego kryteriów: {title}\nSzczegóły: {e}")

    def save_filtered_tender(self, title, link):
        data = {'Tytuł': [title], 'Link': [link]}
        df_new = pd.DataFrame(data)
        try:
            if os.path.exists("filtered_przetargi.xlsx"):
                df_existing = pd.read_excel("filtered_przetargi.xlsx")

                # Sprawdzenie, czy link już istnieje
                if link in df_existing['Link'].values:
                    self.log_message(f"Link już istnieje w pliku: {link}")
                    return

                # Połączenie istniejących danych z nowymi
                df_combined = pd.concat([df_existing, df_new], ignore_index=True)
                df_combined.to_excel("filtered_przetargi.xlsx", index=False)
            else:
                df_new.to_excel("filtered_przetargi.xlsx", index=False)
            self.log_message(f"Zapisano przetarg do pliku filtrowanych przetargów: {title}")
        except Exception as e:
            self.log_message(f"Błąd podczas zapisu przetargu do pliku filtrowanego: {title}\nSzczegóły: {e}")

    def save_all_tender(self, title, link):
        data = {'Tytuł': [title], 'Link': [link]}
        df_new = pd.DataFrame(data)
        try:
            if os.path.exists(EXCEL_FILE):
                df_existing = pd.read_excel(EXCEL_FILE)

                # Sprawdzenie, czy link już istnieje
                if link in df_existing['Link'].values:
                    self.log_message(f"Link już istnieje w pliku: {link}")
                    return

                # Połączenie istniejących danych z nowymi
                df_combined = pd.concat([df_existing, df_new], ignore_index=True)
                df_combined.to_excel(EXCEL_FILE, index=False)
            else:
                df_new.to_excel(EXCEL_FILE, index=False)
            self.log_message(f"Zapisano przetarg do pliku z wszystkimi przetargami: {title}")
        except Exception as e:
            self.log_message(f"Błąd podczas zapisu przetargu do pliku wszystkich przetargów: {title}\nSzczegóły: {e}")

    def add_result_to_view(self, title, link, keyword):
        self.results_tree.insert("", "end", values=(title, link, keyword))

    def log_message(self, message):
        self.log_queue.put(message)  # Zapis logu do kolejki

    def check_log_queue(self):
        try:
            while True:
                message = self.log_queue.get_nowait()
                print(message)  # Logi do konsoli
        except Empty:
            pass
        self.after(100, self.check_log_queue)  # Kontynuuj sprawdzanie co 100 ms

    def is_valid_url(self, url):
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return all([parsed.scheme, parsed.netloc])

    def handle_all_results(self, title, link):
        """Metoda obsługująca wszystkie przetargi, niezależnie od słów kluczowych."""
        if title not in self.all_data_memory:
            self.all_data_memory.add(title)
            self.save_all_tender(title, link)
            self.log_message(f"Zapisano przetarg bez filtrowania: Tytuł: {title}, Link: {link}")

    def handle_unfiltered_tender(self, title, link):
        if title not in self.all_data_memory:
            self.all_data_memory.add(title)
            self.save_unfiltered_tender(title, link)  # Zapisujemy przetargi niespełniające kryteriów
            self.log_message(f"Zapisano przetarg niespełniający kryteriów: Tytuł: {title}, Link: {link}")


if __name__ == "__main__":
    app = MainWindow()
    app.mainloop()
