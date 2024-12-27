import os
import re
import sys
import json
import subprocess
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
)
from PyQt5.QtGui import QPixmap, QFont, QColor, QKeySequence
from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtWidgets import QShortcut
import fitz  # PyMuPDF
import unicodedata

# --- BM25s imports ---
import bm25s

###############################################################################
# Global variables for corpus and BM25 model
###############################################################################
GLOBAL_CORPUS = []
GLOBAL_BM25_MODEL = None

###############################################################################
# Functions that do not depend on the SearchApp class
###############################################################################
def remove_accents(input_str):
    nfkd_form = unicodedata.normalize('NFD', input_str)
    return ''.join([c for c in nfkd_form if not unicodedata.combining(c)])


def load_corpus_and_initialize_bm25():
    """
    Load all .json files in the current directory into GLOBAL_CORPUS
    and build a BM25 index using the bm25s library.
    """
    global GLOBAL_CORPUS, GLOBAL_BM25_MODEL
    # Clear out any existing data
    GLOBAL_CORPUS.clear()

    # Gather all .json files in the current directory
    json_files = [f for f in os.listdir(".") if f.endswith(".json")]
    if not json_files:
        print("No JSON files found in the current directory.")
        return

    # Load data from each JSON file
    for file_name in json_files:
        with open(file_name, "r", encoding="utf-8") as json_file:
            # Each file is expected to have a list of dicts
            # with at least {'text', 'filename', 'page_number'}
            docs = json.load(json_file)
            GLOBAL_CORPUS.extend(docs)

    if not GLOBAL_CORPUS:
        print("No documents found in any JSON file.")
        return

    print(f"Loaded {len(GLOBAL_CORPUS)} documents total.")

    # Build the BM25 index
    # 1) Create the model
    GLOBAL_BM25_MODEL = bm25s.BM25()

    # 2) Tokenize the corpus
    #    Extract each document's text into a list of strings
    texts = [doc['text'] for doc in GLOBAL_CORPUS]
    tokenized_corpus = bm25s.tokenize(texts, stopwords="en")

    # 3) Index the tokenized documents
    GLOBAL_BM25_MODEL.index(tokenized_corpus)
    print("BM25 model successfully initialized.")


###############################################################################
# A custom QGraphicsView to handle clicking on PDF pages
###############################################################################
class ClickableGraphicsView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_pdf_path = None
        self.current_page = 1

    def set_pdf_details(self, pdf_path, page):
        self.current_pdf_path = pdf_path
        self.current_page = page

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.current_pdf_path:
            try:
                subprocess.run(["xdg-open", self.current_pdf_path])
            except Exception as e:
                print(f"Failed to open PDF: {e}")
        super().mousePressEvent(event)


###############################################################################
# The main GUI application class
###############################################################################
class SearchApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Search Interface with PDF Viewer")

        # These track UI states
        self.current_result_index = 0
        self.results = []        # Will hold (doc_id, score) pairs after search
        self.query_terms = []    # For highlighting
        self.font_size = 12
        self.scale_factor = 1.0

        # Build the GUI
        self.init_ui()

        # You can load the corpus + build BM25 model right away (here),
        # or let the user do it via a button. By default, we do it now.
        load_corpus_and_initialize_bm25()

        # You can display a quick message about the load status:
        if GLOBAL_BM25_MODEL is None or not GLOBAL_CORPUS:
            self.result_display.setText("No corpus or BM25 model available.")
        else:
            self.result_display.setText("Corpus loaded successfully. Ready to search.")

    def init_ui(self):
        container = QWidget()
        layout = QHBoxLayout()

        # Left side layout: search box, buttons, and results display
        left_layout = QVBoxLayout()
        self.query_label = QLabel("Search query:")
        self.query_input = QLineEdit()
        self.query_input.returnPressed.connect(self.search)

        left_layout.addWidget(self.query_label)
        left_layout.addWidget(self.query_input)

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

        left_layout.addLayout(button_layout)

        self.result_display = QTextEdit()
        self.result_display.setReadOnly(True)
        self.result_display.setFont(QFont("Arial", self.font_size))
        left_layout.addWidget(self.result_display)

        # Right side layout: the PDF viewer
        self.graphics_view = ClickableGraphicsView()
        self.graphics_scene = QGraphicsScene()
        self.graphics_view.setScene(self.graphics_scene)

        layout.addLayout(left_layout, 1)
        layout.addWidget(self.graphics_view, 1)
        container.setLayout(layout)
        self.setCentralWidget(container)

        # Status bar at the bottom
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # Keyboard shortcuts for zoom
        QShortcut(QKeySequence("Ctrl+="), self, self.zoom_in)
        QShortcut(QKeySequence("Ctrl+-"), self, self.zoom_out)
        QShortcut(QKeySequence("Ctrl+0"), self, self.reset_zoom)

    def highlight_query_terms(self, text):
        """
        Highlights query terms in the given text by wrapping them in a <span>.
        """
        normalized_text = remove_accents(text)
        highlighted_text = normalized_text
        for term in self.query_terms:
            normalized_term = remove_accents(term)
            highlighted_text = re.sub(
                rf'(?i)\b({re.escape(normalized_term)})\b',
                r'<span style="background-color: yellow;">\1</span>',
                highlighted_text,
            )
        return highlighted_text

    def search(self):
        """
        Perform a search using the global BM25 model on the loaded corpus.
        """
        global GLOBAL_BM25_MODEL, GLOBAL_CORPUS

        query = self.query_input.text().strip()
        if not GLOBAL_CORPUS:
            self.result_display.setText("No corpus loaded.")
            return

        if GLOBAL_BM25_MODEL is None:
            self.result_display.setText("No BM25 model is available.")
            return

        # Convert query string to a list of normalized query terms (for highlighting)
        self.query_terms = [remove_accents(term.lower()) for term in query.split()]

        # Tokenize the query with bm25s
        tokenized_query = bm25s.tokenize(query, stopwords="en")

        # Retrieve results (k = size of corpus => retrieve everything)
        results, scores = GLOBAL_BM25_MODEL.retrieve(tokenized_query, k=len(GLOBAL_CORPUS))

        # The shape of `results` and `scores` is (1, k) for a single query
        self.results = [
            (doc_idx, scores[0, i]) for i, doc_idx in enumerate(results[0])
        ]

        # Show the top-ranked chunk first
        self.current_result_index = 0
        self.show_current_chunk()
        self.status_bar.clearMessage()

    def show_current_chunk(self):
        """
        Display the chunk at self.current_result_index and highlight query terms.
        Also display the corresponding PDF page.
        """
        global GLOBAL_CORPUS

        if not self.results:
            self.result_display.setText("No results found.")
            return

        doc_id, score = self.results[self.current_result_index]
        chunk_data = GLOBAL_CORPUS[doc_id]

        # Highlight the text
        highlighted_chunk = self.highlight_query_terms(chunk_data['text'])

        # Display the result
        self.result_display.setHtml(
            f"<b>Result {self.current_result_index + 1} of {len(self.results)}</b><br>"
            f"<b>Filename:</b> {chunk_data['filename']}<br>"
            f"<b>Page Number:</b> {chunk_data['page_number']}<br>"
            f"<b>Score:</b> {score:.4f}<br><br>{highlighted_chunk}"
        )

        # Display the PDF page
        self.display_pdf_page(chunk_data['filename'], chunk_data['page_number'])

    def display_pdf_page(self, pdf_path, page_number, dpi=150):
        """
        Display the specified page of a PDF, highlighting matched terms.
        """
        try:
            doc = fitz.open(pdf_path)
            page = doc[page_number - 1]

            zoom = dpi / 72
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)

            qt_img = QPixmap()
            qt_img.loadFromData(pix.tobytes("ppm"))

            self.graphics_scene.clear()
            pixmap_item = QGraphicsPixmapItem(qt_img)
            self.graphics_scene.addItem(pixmap_item)

            # Highlight query terms on the PDF
            word_positions = page.get_text("words")
            for word in word_positions:
                normalized_word = remove_accents(word[4])
                if any(normalized_term in normalized_word for normalized_term in self.query_terms):
                    rect = QRectF(
                        word[0] * zoom,
                        word[1] * zoom,
                        (word[2] - word[0]) * zoom,
                        (word[3] - word[1]) * zoom
                    )
                    highlight = QGraphicsRectItem(rect)
                    highlight.setBrush(QColor(255, 255, 0, 128))
                    self.graphics_scene.addItem(highlight)

            self.graphics_view.set_pdf_details(pdf_path, page_number)
            self.graphics_scene.setSceneRect(self.graphics_scene.itemsBoundingRect())
            #self.graphics_view.fitInView(self.graphics_scene.sceneRect(), Qt.KeepAspectRatio)

        except Exception as e:
            self.result_display.setText(f"Error displaying PDF: {e}")

    # -----------  Simple UI helpers for navigation & zoom  -----------
    def zoom_in(self):
        self.scale_factor *= 1.2
        self.graphics_view.scale(1.2, 1.2)

    def zoom_out(self):
        self.scale_factor /= 1.2
        self.graphics_view.scale(1 / 1.2, 1 / 1.2)

    def reset_zoom(self):
        self.graphics_view.resetTransform()
        self.scale_factor = 1.0

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

    def decrease_font_size(self):
        if self.font_size > 1:
            self.font_size -= 1
            self.result_display.setFont(QFont("Arial", self.font_size))


###############################################################################
# Program entry point
###############################################################################
if __name__ == "__main__":
    app = QApplication([])
    window = SearchApp()
    window.resize(1000, 600)
    window.show()
    sys.exit(app.exec_())
