#!/usr/bin/env python3
import os
import sys
import json
import numpy as np

from PyQt5 import QtCore, QtWidgets

# Global flag for batch processing; default is disabled.
BATCH_PROCESSING_ENABLED = False

# ---------------------------
# External library functions
# ---------------------------
import pymupdf4llm

# Check if fastembed library is installed
try:
    from fastembed import TextEmbedding
    FASTEMBED_AVAILABLE = True
except ImportError:
    FASTEMBED_AVAILABLE = False
    TextEmbedding = None

##########################################
# Functions for PDF-to-JSON processing
##########################################

def extract_page_chunks(file_path, log_callback=None):
    """
    Extracts page-length chunks from a PDF file using PyMuPDF4LLM.
    Returns a list of dicts (one per page).
    """
    chunks = []
    try:
        data = pymupdf4llm.to_markdown(file_path, page_chunks=True)
        for page in data:
            chunks.append({
                "text": page["text"],
                "page_number": page.get("metadata", {}).get("page", None),
                "filename": os.path.basename(file_path)
            })
    except Exception as e:
        if log_callback:
            log_callback(f"Error extracting chunks from {file_path}: {e}")
        else:
            print(f"Error extracting chunks from {file_path}: {e}")
    return chunks

def process_pdf_to_json(folder, log_callback):
    """
    Processes all PDF files in the given folder.
    For each PDF file that does not yet have a corresponding JSON file,
    extracts page chunks and saves them as JSON.
    """
    pdf_files = [f for f in os.listdir(folder) if f.lower().endswith(".pdf")]
    total_files = len(pdf_files)
    if total_files == 0:
        log_callback(f"No PDF files found in {folder}")
        return

    for idx, file_name in enumerate(pdf_files):
        log_callback(f"Processing PDF file {idx + 1} of {total_files}: {file_name}")
        pdf_file_path = os.path.join(folder, file_name)
        json_file_name = os.path.splitext(file_name)[0] + ".json"
        json_file_path = os.path.join(folder, json_file_name)
        if os.path.exists(json_file_path):
            log_callback(f"Skipping {file_name} – JSON already exists.")
            continue
        try:
            chunks = extract_page_chunks(pdf_file_path, log_callback)
            with open(json_file_path, "w", encoding="utf-8") as json_file:
                json.dump(chunks, json_file, ensure_ascii=False, indent=2)
            log_callback(f"Saved JSON to {json_file_name}")
        except Exception as e:
            log_callback(f"Error processing {file_name}: {e}")

##########################################
# Functions for JSON-to-EMB processing
##########################################

def embed_pages_in_json(json_file_path, embedding_model, log_callback):
    """
    Reads a JSON file containing text chunks (pages),
    generates embeddings for each chunk (using the given embedding_model) one page at a time,
    removes the text field, and returns the updated list.
    """
    with open(json_file_path, "r", encoding="utf-8") as json_file:
        pages = json.load(json_file)

    total_pages = len(pages)
    for i, page in enumerate(pages):
        log_callback(f"Embedding page {i + 1} of {total_pages} in {os.path.basename(json_file_path)}")
        if "text" in page:
            try:
                embedding_gen = embedding_model.passage_embed([page["text"]])
                embedding = list(embedding_gen)[0]
                if isinstance(embedding, np.ndarray):
                    page["embedding"] = embedding.tolist()
                else:
                    page["embedding"] = embedding
            except Exception as e:
                log_callback(f"Error embedding page {i + 1} in {json_file_path}: {e}")
            del page["text"]
    return pages

def embed_pages_in_json_batch(json_file_path, embedding_model, log_callback):
    """
    Batch embeds all pages from the JSON file at once.
    If an error occurs, falls back to page-by-page processing.
    """
    with open(json_file_path, "r", encoding="utf-8") as json_file:
        pages = json.load(json_file)

    total_pages = len(pages)
    texts = []
    for i, page in enumerate(pages):
        texts.append(page.get("text", ""))
    try:
        log_callback(f"Batch embedding {total_pages} pages from {os.path.basename(json_file_path)}")
        embedding_gen = embedding_model.passage_embed(texts)
        embeddings = list(embedding_gen)
        for i, embedding in enumerate(embeddings):
            if isinstance(embedding, np.ndarray):
                pages[i]["embedding"] = embedding.tolist()
            else:
                pages[i]["embedding"] = embedding
            if "text" in pages[i]:
                del pages[i]["text"]
    except Exception as e:
        log_callback(f"Batch embedding error for {os.path.basename(json_file_path)}: {e}")
        log_callback("Falling back to page-by-page embedding for this file.")
        pages = embed_pages_in_json(json_file_path, embedding_model, log_callback)
    return pages

def process_json_to_emb(folder, log_callback):
    """
    Processes all JSON files in the folder.
    For each JSON file that does not have a corresponding .emb file,
    generates embeddings and saves the result as a .emb file.
    """
    if not FASTEMBED_AVAILABLE:
        log_callback("Fastembed library not installed, EMB files creation disabled.")
        return

    try:
        embedding_model = TextEmbedding(model_name="nomic-ai/nomic-embed-text-v1")
    except Exception as e:
        log_callback(f"Error initializing embedding model: {e}")
        return

    json_files = [f for f in os.listdir(folder) if f.lower().endswith(".json")]
    total_files = len(json_files)
    if total_files == 0:
        log_callback(f"No JSON files found in {folder}")
        return

    for idx, file_name in enumerate(json_files):
        emb_file_name = os.path.splitext(file_name)[0] + ".emb"
        emb_file_path = os.path.join(folder, emb_file_name)
        json_file_path = os.path.join(folder, file_name)
        log_callback(f"Processing JSON file {idx + 1} of {total_files}: {file_name}")
        if os.path.exists(emb_file_path):
            log_callback(f"Skipping {file_name} – EMB already exists.")
            continue
        try:
            if BATCH_PROCESSING_ENABLED:
                embedded_pages = embed_pages_in_json_batch(json_file_path, embedding_model, log_callback)
            else:
                embedded_pages = embed_pages_in_json(json_file_path, embedding_model, log_callback)
            with open(emb_file_path, "w", encoding="utf-8") as emb_file:
                json.dump(embedded_pages, emb_file, ensure_ascii=False, indent=2)
            log_callback(f"Saved EMB to {emb_file_name}")
        except Exception as e:
            log_callback(f"Error processing {file_name} for EMB: {e}")

##########################################
# Combined processing per folder (Ordered)
##########################################

def process_folder(folder, process_json, process_emb, log_callback):
    """
    Processes a single folder in a strict order.
    If process_json is True, run PDF-to-JSON extraction.
    Then, if process_emb is True, run JSON-to-EMB creation.
    This order ensures that EMB processing is done only after JSON files are generated.
    """
    log_callback(f"--- Starting processing for folder: {folder} ---")
    if process_json:
        log_callback(">>> Starting PDF-to-JSON extraction...")
        process_pdf_to_json(folder, log_callback)
    else:
        log_callback(">>> Skipping PDF-to-JSON extraction (not selected).")
    
    if process_emb:
        log_callback(">>> Starting JSON-to-EMB creation (after JSON extraction)...")
        process_json_to_emb(folder, log_callback)
    else:
        log_callback(">>> Skipping JSON-to-EMB creation (not selected).")
    
    log_callback(f"--- Finished processing folder: {folder} ---\n")

##########################################
# Worker for Background Processing (PyQt5)
##########################################

class Worker(QtCore.QObject):
    logSignal = QtCore.pyqtSignal(str)
    progressSignal = QtCore.pyqtSignal(int)
    finishedSignal = QtCore.pyqtSignal()

    def __init__(self, queue_items, parent=None):
        super().__init__(parent)
        self.queue_items = queue_items

    @QtCore.pyqtSlot()
    def run(self):
        total = len(self.queue_items)
        for i, item in enumerate(self.queue_items):
            folder = item["folder"]
            process_json = item["process_json"]
            process_emb = item["process_emb"]
            self.logSignal.emit(f"\n=== Processing folder {i + 1} of {total}: {folder} ===")
            process_folder(folder, process_json, process_emb, self.logSignal.emit)
            progress_percent = int(((i + 1) / total) * 100)
            self.progressSignal.emit(progress_percent)
        self.logSignal.emit("\nAll processing complete.")
        self.finishedSignal.emit()

##########################################
# Main Application Window (PyQt5)
##########################################

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Processing Application")
        self.resize(800, 600)
        self.setup_ui()
        self.worker_thread = None

        # If fastembed is not available, display a message in the log
        if not FASTEMBED_AVAILABLE:
            self.append_log("Fastembed library not installed, EMB files creation disabled.")

    def setup_ui(self):
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QtWidgets.QVBoxLayout(central_widget)

        # --- Top Buttons (Add Folder, Clear Queue) ---
        button_layout = QtWidgets.QHBoxLayout()
        self.add_button = QtWidgets.QPushButton("Add Folder")
        self.add_button.clicked.connect(self.add_folder)
        button_layout.addWidget(self.add_button)

        self.clear_button = QtWidgets.QPushButton("Clear Queue")
        self.clear_button.clicked.connect(self.clear_queue)
        button_layout.addWidget(self.clear_button)
        main_layout.addLayout(button_layout)

        # --- Options Layout ---
        options_layout = QtWidgets.QHBoxLayout()
        self.batch_checkbox = QtWidgets.QCheckBox("Batch processing")
        self.batch_checkbox.setToolTip("Faster EMB creation but can run out of memory, disable if program crashes")
        self.batch_checkbox.setChecked(False)
        self.batch_checkbox.toggled.connect(self.update_batch_processing)
        options_layout.addWidget(self.batch_checkbox)
        main_layout.addLayout(options_layout)

        # --- Queue Table ---
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Folder", "Process JSON", "Process EMB", "Actions"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        main_layout.addWidget(self.table)

        # --- Start Processing and Progress Bar ---
        process_layout = QtWidgets.QHBoxLayout()
        self.start_button = QtWidgets.QPushButton("Start Processing")
        self.start_button.clicked.connect(self.start_processing)
        process_layout.addWidget(self.start_button)

        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setValue(0)
        process_layout.addWidget(self.progress_bar)
        main_layout.addLayout(process_layout)

        # --- Log Text Area ---
        self.log_text = QtWidgets.QTextEdit()
        self.log_text.setReadOnly(True)
        main_layout.addWidget(self.log_text)

    def update_batch_processing(self, state):
        global BATCH_PROCESSING_ENABLED
        BATCH_PROCESSING_ENABLED = state

    def add_folder(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            row_position = self.table.rowCount()
            self.table.insertRow(row_position)
            folder_item = QtWidgets.QTableWidgetItem(folder)
            self.table.setItem(row_position, 0, folder_item)
            json_checkbox = QtWidgets.QCheckBox()
            json_checkbox.setChecked(True)
            self.table.setCellWidget(row_position, 1, json_checkbox)
            emb_checkbox = QtWidgets.QCheckBox()
            if not FASTEMBED_AVAILABLE:
                emb_checkbox.setChecked(False)
                emb_checkbox.setEnabled(False)
            else:
                emb_checkbox.setChecked(True)
            self.table.setCellWidget(row_position, 2, emb_checkbox)
            def update_emb(checked, emb=emb_checkbox):
                emb.setEnabled(checked and FASTEMBED_AVAILABLE)
                if not (checked and FASTEMBED_AVAILABLE):
                    emb.setChecked(False)
            json_checkbox.toggled.connect(update_emb)
            remove_button = QtWidgets.QPushButton("Remove")
            remove_button.clicked.connect(lambda _, row=row_position: self.remove_row(row))
            self.table.setCellWidget(row_position, 3, remove_button)

    def remove_row(self, row):
        self.table.removeRow(row)
        for r in range(self.table.rowCount()):
            widget = self.table.cellWidget(r, 3)
            if widget:
                try:
                    widget.clicked.disconnect()
                except Exception:
                    pass
                widget.clicked.connect(lambda checked, row=r: self.remove_row(row))

    def clear_queue(self):
        self.table.setRowCount(0)

    def append_log(self, message):
        self.log_text.append(message)

    def update_progress(self, percent):
        self.progress_bar.setValue(percent)

    def start_processing(self):
        if self.table.rowCount() == 0:
            self.append_log("No folders in queue.")
            return

        self.start_button.setEnabled(False)
        queue_items = []
        for row in range(self.table.rowCount()):
            folder = self.table.item(row, 0).text()
            json_widget = self.table.cellWidget(row, 1)
            emb_widget = self.table.cellWidget(row, 2)
            process_json = json_widget.isChecked() if json_widget else False
            process_emb = emb_widget.isChecked() if emb_widget else False
            queue_items.append({
                "folder": folder,
                "process_json": process_json,
                "process_emb": process_emb
            })

        self.worker = Worker(queue_items)
        self.worker_thread = QtCore.QThread()
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.logSignal.connect(self.append_log)
        self.worker.progressSignal.connect(self.update_progress)
        self.worker.finishedSignal.connect(self.on_processing_finished)
        self.worker.finishedSignal.connect(self.worker_thread.quit)
        self.worker.finishedSignal.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.on_thread_finished)
        self.worker_thread.start()

    def on_processing_finished(self):
        self.append_log("\nAll processing finished.")
        self.start_button.setEnabled(True)

    def on_thread_finished(self):
        self.worker_thread = None

    def closeEvent(self, event):
        if self.worker_thread is not None and self.worker_thread.isRunning():
            self.worker_thread.quit()
            self.worker_thread.wait()
        event.accept()

##########################################
# Main
##########################################

def main():
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
