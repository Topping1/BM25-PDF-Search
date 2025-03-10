import os
import re
import sys
import json
import subprocess
import platform 
import numpy as np
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QPushButton,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QStatusBar,
    QComboBox,
    QShortcut,
    QScrollBar,
    QMenuBar,
    QAction,
    QTableWidget,
    QTableWidgetItem,
    QCheckBox,
    QFileDialog,
    QDialog,
    QDialogButtonBox,
    QMessageBox,
    QAbstractItemView,
    QSplitter
)
from PyQt5.QtGui import QPixmap, QFont, QColor, QKeySequence
from PyQt5.QtCore import Qt, QRectF
import fitz  # PyMuPDF
import unicodedata

# --- BM25s imports ---
import bm25s

###############################################################################
# Attempt fastembed import
###############################################################################
FASTEMBED_AVAILABLE = False
FASTEMBED_ENCODER = None

try:
    from fastembed import TextEmbedding
    FASTEMBED_AVAILABLE = True
except ImportError:
    TextEmbedding = None

###############################################################################
# Global variables for corpus and BM25 model
###############################################################################
GLOBAL_CORPUS = []
GLOBAL_BM25_MODEL = None

# We'll store a fastembed.TextEmbedding model here if needed
GLOBAL_EMBED_MODEL = None

# The maximum number of BM25 search hits to return before any re-ranking.
MAX_SEARCH_RESULTS = 50

# For convenience, we store the folders database in memory (list of dicts):
FOLDERS_DB = []

###############################################################################
# Helper functions
###############################################################################
def remove_accents(input_str):
    nfkd_form = unicodedata.normalize('NFD', input_str)
    return ''.join([c for c in nfkd_form if not unicodedata.combining(c)])

def load_folders_database():
    """
    Attempts to load 'folders.ini'. 
    If it doesn't exist, returns None => "not initialized".
    If it exists but is invalid or empty, returns empty list => valid but no data.
    Otherwise, returns the list.
    """
    if not os.path.exists("folders.ini"):
        return None

    try:
        with open("folders.ini", "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, list):
                # If the JSON is not a list, treat it as invalid
                return []
            return data
    except Exception as e:
        print(f"Error reading folders.ini: {e}")
        return []

def save_folders_database(folders_list):
    """
    Saves the given folders_list to 'folders.ini'.
    """
    try:
        with open("folders.ini", "w", encoding="utf-8") as f:
            json.dump(folders_list, f, indent=2)
    except Exception as e:
        print(f"Error writing folders.ini: {e}")

def load_corpus_and_initialize_bm25(folders_list):
    """
    Given a list of folder entries (each with {checked, path, description}),
    load all .json (and matching .emb) from the *checked* folders into GLOBAL_CORPUS,
    and build a BM25 index.
    
    If a folder does not exist, we store "Folder xxxxxx not found" in error_messages.
    Returns (error_messages, status_message).
    """
    global GLOBAL_CORPUS, GLOBAL_BM25_MODEL

    GLOBAL_CORPUS.clear()
    GLOBAL_BM25_MODEL = None
    error_messages = []

    # Collect all JSON files from the checked folders
    all_json_files = []
    for folder_entry in folders_list:
        if not folder_entry.get("checked"):
            continue
        folder_path = folder_entry.get("path", "")
        if not os.path.isdir(folder_path):
            # Folder not found
            error_messages.append(f"Folder {folder_path} not found")
            continue

        json_files_in_folder = [
            os.path.join(folder_path, f) for f in os.listdir(folder_path) 
            if f.endswith(".json")
        ]
        all_json_files.extend(json_files_in_folder)

    if not all_json_files:
        return error_messages, "No JSON files found in the selected folders."

    # Load data from each JSON file
    for file_path in all_json_files:
        try:
            with open(file_path, "r", encoding="utf-8") as json_file:
                docs = json.load(json_file)

            # For each doc, if 'filename' is given, make it absolute
            folder_of_json = os.path.dirname(file_path)
            for doc in docs:
                pdf_name = doc.get('filename', '')
                if pdf_name and not os.path.isabs(pdf_name):
                    doc['filename'] = os.path.join(folder_of_json, pdf_name)

            GLOBAL_CORPUS.extend(docs)
        except Exception as e:
            error_messages.append(f"Error reading {file_path}: {e}")

    if not GLOBAL_CORPUS:
        return error_messages, "No documents found in any JSON file."

    # Build BM25 index
    texts = [doc['text'] for doc in GLOBAL_CORPUS if 'text' in doc]
    if texts:
        GLOBAL_BM25_MODEL = bm25s.BM25()
        tokenized_corpus = bm25s.tokenize(texts, stopwords="en")
        GLOBAL_BM25_MODEL.index(tokenized_corpus)
    else:
        return error_messages, "No textual data to build BM25 model."

    # Attempt to load embeddings for each JSON
    load_embeddings_for_corpus(all_json_files)
    return error_messages, "BM25 model successfully initialized."

def load_embeddings_for_corpus(json_file_list):
    """
    For each .json file in 'json_file_list', tries to find a matching .emb file
    in the same folder with the same base name. If present, load the embeddings.
    """
    global GLOBAL_CORPUS
    emb_count = 0
    corpus_index = 0

    for file_path in json_file_list:
        base, _ext = os.path.splitext(file_path)
        emb_file_path = base + ".emb"

        # Count how many pages are in this JSON
        try:
            with open(file_path, "r", encoding="utf-8") as j:
                pages_in_json = json.load(j)
        except:
            pages_in_json = []
        num_pages = len(pages_in_json)

        if not os.path.exists(emb_file_path):
            # Just move corpus_index forward
            corpus_index += num_pages
            continue

        # We found a .emb file
        try:
            with open(emb_file_path, "r", encoding="utf-8") as emb_file:
                pages_with_emb = json.load(emb_file)
        except:
            pages_with_emb = []

        if len(pages_in_json) != len(pages_with_emb):
            print(f"Warning: mismatch in #pages for {file_path} vs {emb_file_path}")
            min_len = min(len(pages_in_json), len(pages_with_emb))
        else:
            min_len = len(pages_in_json)

        # Attach embeddings
        for i in range(min_len):
            doc = GLOBAL_CORPUS[corpus_index + i]
            if 'embedding' in pages_with_emb[i]:
                doc['embedding'] = np.array(pages_with_emb[i]['embedding'], dtype=np.float32)
                emb_count += 1

        corpus_index += num_pages

    print(f"Loaded embeddings for {emb_count} pages total.")


###############################################################################
# Minimal span-based scoring functions (unchanged)
###############################################################################
def minimal_span_score(text, query_terms):
    norm_text = remove_accents(text.lower())
    norm_query_terms = [remove_accents(qt.lower()) for qt in query_terms]

    words = norm_text.split()
    positions = {term: [] for term in norm_query_terms}
    for i, w in enumerate(words):
        if w in positions:
            positions[w].append(i)

    for term in norm_query_terms:
        if not positions[term]:
            return 0.0

    all_positions = []
    for t in norm_query_terms:
        all_positions.extend((p, t) for p in positions[t])
    all_positions.sort(key=lambda x: x[0])

    best_span = len(words) + 1
    found_terms = {}
    left = 0
    for right in range(len(all_positions)):
        pos_right, term_right = all_positions[right]
        found_terms[term_right] = pos_right

        while len(found_terms) == len(norm_query_terms):
            span = max(found_terms.values()) - min(found_terms.values()) + 1
            if span < best_span:
                best_span = span
            pos_left, term_left = all_positions[left]
            if found_terms.get(term_left, None) == pos_left:
                del found_terms[term_left]
            left += 1

    return 1.0 / (best_span + 1)

def rerank_minimal_span(top_docs, query_terms):
    global GLOBAL_CORPUS
    doc_scores = []
    for doc_id, bm25_score in top_docs:
        text = GLOBAL_CORPUS[doc_id]['text']
        ms_score = minimal_span_score(text, query_terms)
        doc_scores.append((doc_id, ms_score))
    doc_scores.sort(key=lambda x: x[1], reverse=True)
    return doc_scores

###############################################################################
# Exact text search (unchanged)
###############################################################################
def rerank_exact_text(top_docs, query_phrase):
    global GLOBAL_CORPUS
    query_norm = remove_accents(query_phrase.lower())
    matched = []
    unmatched = []

    for doc_id, bm25_score in top_docs:
        doc_text = GLOBAL_CORPUS[doc_id]['text']
        doc_text_norm = remove_accents(doc_text.lower())
        if query_norm in doc_text_norm:
            matched.append((doc_id, bm25_score))
        else:
            unmatched.append((doc_id, bm25_score))

    return matched + unmatched

###############################################################################
# Helper function for "Simple text search"
###############################################################################
def parse_simple_search_query(query_str):
    pattern = r'"([^"]+)"|(\S+)'
    matches = re.findall(pattern, query_str)

    quoted_phrases = []
    unquoted_words = []
    for (phrase, word) in matches:
        if phrase:
            quoted_phrases.append(phrase)
        elif word:
            unquoted_words.append(word)
    return quoted_phrases, unquoted_words

###############################################################################
# A custom QGraphicsView to handle clicking on PDF pages (unchanged)
###############################################################################
class ClickableGraphicsView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_pdf_path = None
        self.current_page = 1
        self.total_pages = 1

    def set_pdf_details(self, pdf_path, page, total_pages):
        self.current_pdf_path = pdf_path
        self.current_page = page
        self.total_pages = total_pages

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.current_pdf_path:
            try:
                if platform.system() == "Windows":
                    # Call Adobe Acrobat Reader on Windows.
                    subprocess.run([
                        "AcroRd32.exe",
                        "/A", f"page={self.current_page}",
                        self.current_pdf_path
                    ])
                else:
                    # Use Okular on Linux.
                    subprocess.run([
                        "okular",
                        self.current_pdf_path,
                        "-p",
                        str(self.current_page)
                    ])
            except Exception as e:
                print(f"Failed to open PDF: {e}")
        super().mousePressEvent(event)

###############################################################################
# Dialog for managing folders
###############################################################################
class FoldersDialog(QDialog):
    def __init__(self, folders_list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Data Folders")
        self.folders_list = folders_list  # We'll work on a copy in memory

        # Make this window 3× wider (arbitrary choice: 1200x600)
        self.resize(1200, 600)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Load?", "Folder Path", "Description"])
        self.table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)

        self.load_data_into_table()

        # Buttons
        button_layout = QHBoxLayout()
        self.add_button = QPushButton("Add folder")
        self.remove_button = QPushButton("Remove folder")
        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.remove_button)

        self.add_button.clicked.connect(self.add_folder_row)
        self.remove_button.clicked.connect(self.remove_folder_row)

        # OK / Cancel
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept_dialog)
        self.button_box.rejected.connect(self.reject_dialog)

        # Layout
        main_layout = QVBoxLayout()
        main_layout.addWidget(self.table)
        main_layout.addLayout(button_layout)
        main_layout.addWidget(self.button_box)
        self.setLayout(main_layout)

        # Make it modal
        self.setModal(True)

    def load_data_into_table(self):
        self.table.setRowCount(len(self.folders_list))
        for row, folder_entry in enumerate(self.folders_list):
            # Column 0: checkbox
            check_box = QCheckBox()
            check_box.setChecked(bool(folder_entry.get("checked", False)))
            self.table.setCellWidget(row, 0, check_box)

            # Column 1: folder path
            path_item = QTableWidgetItem(folder_entry.get("path", ""))
            self.table.setItem(row, 1, path_item)

            # Column 2: description
            desc_item = QTableWidgetItem(folder_entry.get("description", ""))
            self.table.setItem(row, 2, desc_item)

    def add_folder_row(self):
        row = self.table.rowCount()
        self.table.insertRow(row)

        check_box = QCheckBox()
        check_box.setChecked(True)
        self.table.setCellWidget(row, 0, check_box)

        folder_path_item = QTableWidgetItem("")
        self.table.setItem(row, 1, folder_path_item)

        desc_item = QTableWidgetItem("")
        self.table.setItem(row, 2, desc_item)

        # Optionally open a file dialog right away
        folder = QFileDialog.getExistingDirectory(self, "Select Folder", "")
        if folder:
            folder_path_item.setText(folder)

    def remove_folder_row(self):
        current_row = self.table.currentRow()
        if current_row >= 0:
            self.table.removeRow(current_row)

    def accept_dialog(self):
        new_folders = []
        for row in range(self.table.rowCount()):
            w = self.table.cellWidget(row, 0)
            checked = w.isChecked() if w else False

            path_item = self.table.item(row, 1)
            path = path_item.text() if path_item else ""

            desc_item = self.table.item(row, 2)
            desc = desc_item.text() if desc_item else ""

            # If user didn't pick a path, prompt now
            if not path:
                folder = QFileDialog.getExistingDirectory(self, "Select Folder", "")
                path = folder

            new_folders.append({
                "checked": checked,
                "path": path,
                "description": desc,
            })

        self.folders_list[:] = new_folders  # update in place
        super().accept()

    def reject_dialog(self):
        super().reject()

###############################################################################
# The main GUI application class
###############################################################################
class SearchApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Search Interface with PDF Viewer")
        self.current_result_index = 0
        self.results = []
        # We'll keep a dynamic list of words to highlight in the PDF
        self.query_terms = []
        self.font_size = 12
        self.scale_factor = 1.0

        self.embeddings_present = False  # whether we found .emb files
        self.init_ui()

        # ---------------------------------------------------------------------
        # Load the folders database if available; if not, message the user
        # ---------------------------------------------------------------------
        global FOLDERS_DB
        loaded_data = load_folders_database()
        if loaded_data is None:
            # None => "folders.ini" not found
            self.result_display.setText("Folder database not initialized")
            FOLDERS_DB = []
        else:
            FOLDERS_DB = loaded_data

        # If we have a valid list, attempt to load the corpus
        if FOLDERS_DB:
            errors, status = load_corpus_and_initialize_bm25(FOLDERS_DB)
            # Show any error messages (e.g. missing folders)
            for err in errors:
                self.result_display.append(err)
            self.result_display.append(status)
        # If FOLDERS_DB is empty and not None, it means folders.ini was present but invalid or empty
        if FOLDERS_DB == [] and loaded_data is not None:
            self.result_display.setText("No folders in database. Please add some folders.")

        # Check if we actually loaded any embeddings
        self.embeddings_present = any(('embedding' in doc) for doc in GLOBAL_CORPUS)

        # Attempt to initialize the global embedding model if we have embeddings
        global GLOBAL_EMBED_MODEL, FASTEMBED_AVAILABLE
        if self.embeddings_present:
            if FASTEMBED_AVAILABLE:
                GLOBAL_EMBED_MODEL = TextEmbedding(model_name="nomic-ai/nomic-embed-text-v1")
                if GLOBAL_BM25_MODEL is not None:
                    self.result_display.append("Corpus and Embeddings loaded successfully. Ready to search.")
                else:
                    self.result_display.append("Embeddings loaded successfully (no BM25). Ready to search.")
            else:
                if GLOBAL_BM25_MODEL is not None:
                    self.result_display.append("FastEmbed not installed. Embeddings won't be used.")
                else:
                    self.result_display.append("No BM25 and no FastEmbed. Check your installation.")
        else:
            if GLOBAL_BM25_MODEL is None:
                self.result_display.setText("No corpus or BM25 model available.")
            else:
                self.result_display.append("Corpus loaded successfully. Ready to search.")

    def init_ui(self):
        # MENU
        menubar = self.menuBar()
        data_folders_menu = menubar.addMenu("Data folders")
        manage_folders_action = QAction("Manage folders...", self)
        manage_folders_action.triggered.connect(self.on_manage_folders)
        data_folders_menu.addAction(manage_folders_action)

        # ---------------------------------------------------------------------
        # Instead of a simple layout, use a QSplitter with vertical orientation
        # so top = text area, bottom = PDF viewer
        # ---------------------------------------------------------------------
        splitter = QSplitter(Qt.Horizontal)

        # Top widget (text area)
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)

        # Row for "Search method" and "Reranking method"
        top_row_layout = QHBoxLayout()

        self.search_method_label = QLabel("Search method:")
        self.search_method_combo = QComboBox()
        self.search_method_combo.addItem("BM25")
        self.search_method_combo.addItem("Simple text search")
        self.search_method_combo.addItem("Embeddings search")
        self.search_method_combo.currentIndexChanged.connect(self.update_rerank_combo_status)

        top_row_layout.addWidget(self.search_method_label)
        top_row_layout.addWidget(self.search_method_combo)

        self.rerank_label = QLabel("Reranking method:")
        self.rerank_combo = QComboBox()
        self.rerank_combo.addItem("No reranking")
        self.rerank_combo.addItem("Minimal span-based scoring")
        self.rerank_combo.addItem("Exact text search")
        self.rerank_combo.addItem("Embeddings rerank")
        self.rerank_combo.setEditable(False)
        self.rerank_combo.currentIndexChanged.connect(self.search)

        top_row_layout.addWidget(self.rerank_label)
        top_row_layout.addWidget(self.rerank_combo)

        top_layout.addLayout(top_row_layout)

        # Search label/input
        self.query_label = QLabel("Search query:")
        self.query_input = QLineEdit()
        self.query_input.setFont(QFont("Arial", self.font_size))
        self.query_input.returnPressed.connect(self.search)
        top_layout.addWidget(self.query_label)
        top_layout.addWidget(self.query_input)

        # Navigation buttons
        button_layout = QHBoxLayout()
        self.prev_button = QPushButton("<--")
        self.next_button = QPushButton("-->")
        self.prev_button.clicked.connect(self.show_previous_chunk)
        self.next_button.clicked.connect(self.show_next_chunk)
        button_layout.addWidget(self.prev_button)
        button_layout.addWidget(self.next_button)

        self.decrease_font_button = QPushButton("-")
        self.decrease_font_button.clicked.connect(self.decrease_font_size)
        button_layout.addWidget(self.decrease_font_button)

        self.increase_font_button = QPushButton("+")
        self.increase_font_button.clicked.connect(self.increase_font_size)
        button_layout.addWidget(self.increase_font_button)
        
        # --- New checkbox for toggling PDF cropping ---
        self.crop_pdf_view_checkbox = QCheckBox("Crop PDF view")
        self.crop_pdf_view_checkbox.setChecked(True)
        self.crop_pdf_view_checkbox.toggled.connect(self.on_toggle_crop_pdf_view)
        button_layout.addWidget(self.crop_pdf_view_checkbox)
        # -------------------------------------------------

        top_layout.addLayout(button_layout)

        # Results text area
        self.result_display = QTextEdit()
        self.result_display.setReadOnly(True)
        self.result_display.setFont(QFont("Arial", self.font_size))
        top_layout.addWidget(self.result_display)

        splitter.addWidget(top_widget)  # add top widget to splitter

        # Bottom widget (PDF viewer)
        self.graphics_view = ClickableGraphicsView()
        self.graphics_scene = QGraphicsScene()
        self.graphics_view.setScene(self.graphics_scene)
        splitter.addWidget(self.graphics_view)

        # Set the initial proportions (e.g., 30% for the left and 70% for the right)
        splitter.setSizes([30, 700])  # Proportions are in pixels but will scale proportionally

        # Let both splitter panes expand or shrink
        splitter.setStretchFactor(0, 1)  # top
        splitter.setStretchFactor(1, 1)  # bottom

        # Create a container layout to hold just the splitter
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.addWidget(splitter)

        self.setCentralWidget(container)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # Shortcuts
        QShortcut(QKeySequence(Qt.Key_PageUp), self, self.page_up)
        QShortcut(QKeySequence(Qt.Key_PageDown), self, self.page_down)
        QShortcut(QKeySequence("Ctrl++"), self, self.zoom_in)
        QShortcut(QKeySequence("Ctrl+-"), self, self.zoom_out)
        QShortcut(QKeySequence("Ctrl+0"), self, self.reset_zoom)

        QShortcut(QKeySequence("Alt+Left"), self, self.show_previous_chunk)
        QShortcut(QKeySequence("Alt+Right"), self, self.show_next_chunk)

        # PDF scrolling shortcuts
        QShortcut(QKeySequence("Ctrl+Left"), self, self.scroll_pdf_left)
        QShortcut(QKeySequence("Ctrl+Right"), self, self.scroll_pdf_right)
        QShortcut(QKeySequence("Ctrl+Up"), self, self.scroll_pdf_up)
        QShortcut(QKeySequence("Ctrl+Down"), self, self.scroll_pdf_down)

        # Set initial status for Reranking combo
        self.update_rerank_combo_status()

    def on_manage_folders(self):
        """
        Opens the FoldersDialog to manage the folders. 
        If the user clicks OK, we update 'folders.ini' and reload the corpus.
        """
        global FOLDERS_DB
        global GLOBAL_EMBED_MODEL
        global FASTEMBED_AVAILABLE

        dialog = FoldersDialog(folders_list=FOLDERS_DB.copy(), parent=self)
        result = dialog.exec_()
        if result == QDialog.Accepted:
            save_folders_database(dialog.folders_list)
            FOLDERS_DB = dialog.folders_list

            # Reload the corpus
            GLOBAL_CORPUS.clear()
            errors, status = load_corpus_and_initialize_bm25(FOLDERS_DB)
            self.result_display.clear()
            for err in errors:
                self.result_display.append(err)
            self.result_display.append(status)

            # Check if embeddings are present
            self.embeddings_present = any(('embedding' in doc) for doc in GLOBAL_CORPUS)
            if self.embeddings_present and FASTEMBED_AVAILABLE:
                if GLOBAL_EMBED_MODEL is None:
                    self.result_display.append("Initializing embedding model...")
                    GLOBAL_EMBED_MODEL = TextEmbedding(model_name="nomic-ai/nomic-embed-text-v1")
                self.result_display.append("Folders updated. Corpus and embeddings loaded.")
            else:
                if self.embeddings_present and not FASTEMBED_AVAILABLE:
                    self.result_display.append("Folders updated. Embeddings found, but fastembed is not installed.")
                else:
                    self.result_display.append("Folders updated.")
        else:
            # user canceled => do nothing
            pass

    def update_rerank_combo_status(self):
        current_method = self.search_method_combo.currentText()
        if current_method == "BM25":
            self.rerank_combo.setEnabled(True)
        elif current_method == "Simple text search":
            self.rerank_combo.setEnabled(False)
        elif current_method == "Embeddings search":
            self.rerank_combo.setEnabled(False)
        else:
            self.rerank_combo.setEnabled(True)

    # -------------------------------------------------------------------------
    # PDF display and navigation
    # -------------------------------------------------------------------------
    def display_pdf_page(self, pdf_path, page_number):
        try:
            doc = fitz.open(pdf_path)
            page = doc[page_number - 1]

            # Apply cropping if enabled, else reset to full page view
            if self.crop_pdf_view_checkbox.isChecked():
                # Calculate the bounding box of all text blocks
                text_blocks = page.get_text("blocks")
                if not text_blocks:
                    print("No text found on the page.")
                    return

                # Initialize bounding box coordinates
                x_min = float('inf')
                y_min = float('inf')
                x_max = float('-inf')
                y_max = float('-inf')

                # Determine the bounding box encompassing all text
                for block in text_blocks:
                    x0, y0, x1, y1 = block[:4]
                    x_min = min(x_min, x0)
                    y_min = min(y_min, y0)
                    x_max = max(x_max, x1)
                    y_max = max(y_max, y1)

                # Define the new crop box
                crop_box = fitz.Rect(x_min, y_min, x_max, y_max)

                # Retrieve the media box
                media_box = page.mediabox

                # Check if the crop box is within the media box
                if (crop_box.x0 >= media_box.x0 and crop_box.y0 >= media_box.y0 and
                    crop_box.x1 <= media_box.x1 and crop_box.y1 <= media_box.y1):
                    # Set the crop box if it's valid
                    page.set_cropbox(crop_box)
                else:
                    print("Calculated crop box is not within the media box. Rendering the full page.")
            else:
                # If cropping is disabled, ensure the full page is shown.
                page.set_cropbox(page.mediabox)

            # Render the page
            base_dpi = 150  # base DPI for default zoom
            dpi = base_dpi * self.scale_factor
            zoom = dpi / 72
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)

            # Convert to QPixmap for display
            qt_img = QPixmap()
            qt_img.loadFromData(pix.tobytes("ppm"))

            # Display the image in the graphics scene
            self.graphics_scene.clear()
            pixmap_item = QGraphicsPixmapItem(qt_img)
            self.graphics_scene.addItem(pixmap_item)

            # Highlight search terms
            word_positions = page.get_text("words")
            for word in word_positions:
                raw_word = word[4].lower()
                raw_word = remove_accents(raw_word)
                raw_word = re.sub(r"[^\w]+", "", raw_word)  # ignore punctuation

                if any(nt == raw_word for nt in self.query_terms):
                    rect = QRectF(word[0] * zoom, word[1] * zoom,
                                  (word[2] - word[0]) * zoom,
                                  (word[3] - word[1]) * zoom)
                    highlight = QGraphicsRectItem(rect)
                    highlight.setBrush(QColor(255, 255, 0, 128))
                    self.graphics_scene.addItem(highlight)

            self.graphics_view.set_pdf_details(pdf_path, page_number, len(doc))
            self.graphics_scene.setSceneRect(self.graphics_scene.itemsBoundingRect())

        except Exception as e:
            self.result_display.setText(f"Error displaying PDF: {e}")

    def on_toggle_crop_pdf_view(self):
        """
        Called when the crop PDF view checkbox is toggled.
        Re-render the current PDF page to apply the new cropping setting.
        """
        if self.graphics_view.current_pdf_path:
            self.display_pdf_page(self.graphics_view.current_pdf_path, self.graphics_view.current_page)

    def page_up(self):
        if self.graphics_view.current_pdf_path and self.graphics_view.current_page > 1:
            self.graphics_view.current_page -= 1
            self.display_pdf_page(self.graphics_view.current_pdf_path, self.graphics_view.current_page)

    def page_down(self):
        if self.graphics_view.current_pdf_path and self.graphics_view.current_page < self.graphics_view.total_pages:
            self.graphics_view.current_page += 1
            self.display_pdf_page(self.graphics_view.current_pdf_path, self.graphics_view.current_page)

    def scroll_pdf_left(self):
        hbar = self.graphics_view.horizontalScrollBar()
        hbar.setValue(hbar.value() - 50)

    def scroll_pdf_right(self):
        hbar = self.graphics_view.horizontalScrollBar()
        hbar.setValue(hbar.value() + 50)

    def scroll_pdf_up(self):
        vbar = self.graphics_view.verticalScrollBar()
        vbar.setValue(vbar.value() - 50)

    def scroll_pdf_down(self):
        vbar = self.graphics_view.verticalScrollBar()
        vbar.setValue(vbar.value() + 50)

    # -------------------------------------------------------------------------
    # Searching
    # -------------------------------------------------------------------------
    def search(self):
        global GLOBAL_BM25_MODEL, GLOBAL_CORPUS, GLOBAL_EMBED_MODEL, FASTEMBED_AVAILABLE

        # Always reset self.query_terms based on the *current* query
        # so that the highlighting matches whatever query was just entered
        raw_query = self.query_input.text().strip()
        self.query_terms = [remove_accents(w.lower()) for w in re.findall(r"\w+", raw_query, flags=re.IGNORECASE)]

        if not GLOBAL_CORPUS:
            self.result_display.setText("No corpus loaded.")
            return

        if not raw_query:
            self.result_display.setText("Please enter a search query.")
            return

        search_method = self.search_method_combo.currentText()
        method = self.rerank_combo.currentText()

        # ---------------------------------------------------------------------
        # CASE 1: "Simple text search"
        # ---------------------------------------------------------------------
        if search_method == "Simple text search":
            quoted_phrases, unquoted_words = parse_simple_search_query(raw_query)

            quoted_phrases_norm = [remove_accents(p.lower()) for p in quoted_phrases]
            unquoted_words_norm = [remove_accents(w.lower()) for w in unquoted_words]

            matches = []
            for idx, doc in enumerate(GLOBAL_CORPUS):
                doc_text_norm = remove_accents(doc['text'].lower()) if 'text' in doc else ""
                # Must contain all quoted multi-word substrings
                if not all(phrase in doc_text_norm for phrase in quoted_phrases_norm):
                    continue
                # Must contain all unquoted words
                if not all(word in doc_text_norm for word in unquoted_words_norm):
                    continue
                matches.append(idx)

            self.results = [(doc_id, 1.0) for doc_id in matches]
            self.current_result_index = 0
            if not self.results:
                self.result_display.setText("No results found.")
            else:
                self.show_current_chunk()
            self.status_bar.clearMessage()
            return

        # ---------------------------------------------------------------------
        # CASE 2: "Embeddings search"
        # (Now we do the penalty *after* we get the top K=MAX_SEARCH_RESULTS)
        # ---------------------------------------------------------------------
        if search_method == "Embeddings search":
            if not self.embeddings_present:
                self.result_display.setText("No .emb files found. Reverting to BM25 search.")
                self.search_method_combo.setCurrentText("BM25")
                return

            if not FASTEMBED_AVAILABLE or GLOBAL_EMBED_MODEL is None:
                self.result_display.setText("FastEmbed library not available. Reverting to BM25 search.")
                self.search_method_combo.setCurrentText("BM25")
                return

            query_embedding = list(GLOBAL_EMBED_MODEL.query_embed(raw_query))[0]  # shape (dim,)

            # Step 1: gather dot-product scores for all docs (ignoring empty pages)
            doc_scores = []
            for idx, doc in enumerate(GLOBAL_CORPUS):
                if 'embedding' not in doc:
                    continue
                text = doc.get('text', '')
                if not text.strip():
                    # skip empty
                    continue

                emb = doc['embedding']
                emb_score = float(np.dot(emb, query_embedding))
                doc_scores.append((idx, emb_score))

            # Step 2: sort by dot-product descending
            doc_scores.sort(key=lambda x: x[1], reverse=True)

            # Step 3: truncate to top K
            top_k = doc_scores[:MAX_SEARCH_RESULTS]

            # Step 4: apply length-penalty to *those* top K and re-sort
            length_penalty_exponent = 0.5
            penalized_scores = []
            for (idx, base_score) in top_k:
                text = GLOBAL_CORPUS[idx].get('text', '')
                length = len(text)
                if length > 0:
                    final_score = base_score * (length ** length_penalty_exponent)
                else:
                    final_score = 0.0
                penalized_scores.append((idx, final_score))

            # Step 5: sort by the penalized score descending
            penalized_scores.sort(key=lambda x: x[1], reverse=True)

            # The final ranking is penalized_scores
            self.results = penalized_scores
            self.current_result_index = 0

            if not self.results:
                self.result_display.setText("No results found.")
            else:
                self.show_current_chunk()
            self.status_bar.clearMessage()
            return

        # ---------------------------------------------------------------------
        # CASE 3: "BM25"
        # ---------------------------------------------------------------------
        if GLOBAL_BM25_MODEL is None:
            self.result_display.setText("No BM25 model is available.")
            return

        tokenized_query = bm25s.tokenize(raw_query, stopwords="en")
        results, scores = GLOBAL_BM25_MODEL.retrieve(tokenized_query, k=len(GLOBAL_CORPUS))
        bm25_ranking = [(doc_idx, scores[0, i]) for i, doc_idx in enumerate(results[0])]
        bm25_ranking.sort(key=lambda x: x[1], reverse=True)
        truncated_ranking = bm25_ranking[:MAX_SEARCH_RESULTS]

        # Rerank if requested
        if method == "No reranking":
            final_ranking = truncated_ranking
        elif method == "Minimal span-based scoring":
            final_ranking = rerank_minimal_span(truncated_ranking, self.query_terms)
        elif method == "Exact text search":
            final_ranking = rerank_exact_text(truncated_ranking, raw_query)
        elif method == "Embeddings rerank":
            if not FASTEMBED_AVAILABLE:
                self.result_display.setText("Fastembed not installed. Cannot do embeddings rerank.")
                final_ranking = truncated_ranking
            else:
                final_ranking = self.rerank_with_embeddings(truncated_ranking, raw_query)
        else:
            final_ranking = truncated_ranking

        self.results = final_ranking
        self.current_result_index = 0

        if not self.results:
            self.result_display.setText("No results found.")
        else:
            self.show_current_chunk()

        self.status_bar.clearMessage()

    def rerank_with_embeddings(self, top_docs, query_phrase):
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        encoder = TextCrossEncoder(model_name="Xenova/ms-marco-MiniLM-L-6-v2")

        documents = [GLOBAL_CORPUS[doc_id]['text'] for (doc_id, _score) in top_docs]
        scores = list(encoder.rerank(query_phrase, documents))

        doc_scores = []
        for (doc_id, _bm25score), embed_score in zip(top_docs, scores):
            doc_scores.append((doc_id, embed_score))

        doc_scores.sort(key=lambda x: x[1], reverse=True)
        return doc_scores

    def show_current_chunk(self):
        global GLOBAL_CORPUS
        if not self.results:
            self.result_display.setText("No results found.")
            return

        doc_id, score = self.results[self.current_result_index]
        chunk_data = GLOBAL_CORPUS[doc_id]

        # We'll highlight them in the chunk text (if any).
        text_to_display = chunk_data.get('text', "")
        highlighted_chunk = self.highlight_query_terms(text_to_display)

        self.result_display.setHtml(
            f"<b>Result {self.current_result_index + 1} of {len(self.results)}</b><br>"
            f"<b>Filename:</b> {chunk_data.get('filename','')}<br>"
            f"<b>Page Number:</b> {chunk_data.get('page_number','')}<br>"
            f"<b>Score:</b> {score:.4f}<br><br>{highlighted_chunk}"
        )

        pdf_path = chunk_data.get('filename','')
        page_number = chunk_data.get('page_number', 1)
        if pdf_path and os.path.exists(pdf_path):
            self.display_pdf_page(pdf_path, page_number)
        else:
            self.result_display.append("<br><i>No PDF or page info available, or PDF not found.</i>")

    def highlight_query_terms(self, text):
        normalized_text = remove_accents(text)
        highlighted_text = normalized_text
        for term in self.query_terms:
            escaped_term = re.escape(term)
            highlighted_text = re.sub(
                rf'(?i)\b({escaped_term})\b',
                r'<span style="background-color: yellow;">\1</span>',
                highlighted_text,
            )
        return highlighted_text

    # -------------------------------------------------------------------------
    # Zoom and font size
    # -------------------------------------------------------------------------
    def zoom_in(self):
        self.scale_factor *= 1.2
        if self.graphics_view.current_pdf_path:
            self.display_pdf_page(self.graphics_view.current_pdf_path, self.graphics_view.current_page)

    def zoom_out(self):
        self.scale_factor /= 1.2
        if self.graphics_view.current_pdf_path:
            self.display_pdf_page(self.graphics_view.current_pdf_path, self.graphics_view.current_page)

    def reset_zoom(self):
        self.scale_factor = 1.0
        if self.graphics_view.current_pdf_path:
            self.display_pdf_page(self.graphics_view.current_pdf_path, self.graphics_view.current_page)

    def show_next_chunk(self):
        if not self.results:
            return
        self.current_result_index = (self.current_result_index + 1) % len(self.results)
        self.show_current_chunk()

    def show_previous_chunk(self):
        if not self.results:
            return
        self.current_result_index = (self.current_result_index - 1) % len(self.results)
        self.show_current_chunk()

    def increase_font_size(self):
        self.font_size += 1
        self.result_display.setFont(QFont("Arial", self.font_size))
        self.query_input.setFont(QFont("Arial", self.font_size))

    def decrease_font_size(self):
        if self.font_size > 1:
            self.font_size -= 1
            self.result_display.setFont(QFont("Arial", self.font_size))
            self.query_input.setFont(QFont("Arial", self.font_size))

###############################################################################
# Program entry point
###############################################################################
if __name__ == "__main__":
    app = QApplication([])
    window = SearchApp()
    window.resize(1000, 700)  # a bit taller, since it's top/bottom
    window.show()
    sys.exit(app.exec_())
