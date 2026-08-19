#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HDF5 Image Divider Plugin with Metadata Viewer for PyQtGraph
-------------------------------------------------------------
Opens HDF5 files virtually and displays the division of two image datasets.
Allows real-time shifting of the second image using keyboard arrows.
Includes slider to select which image index to view.
Added metadata viewer tab to display all HDF5 attributes and datasets.

Structure expected:
- /exchange/data (array of projections - first image)
- /exchange/data_white (array of images - second image)

Shows: data / data_white with real-time shift adjustment
Tab 2: Comprehensive metadata viewer
"""

import os

import h5py
import numpy as np
from PyQt5 import QtWidgets, QtCore, QtGui

from .line import LineProfileManager
from .roi import ROIManager
from .ellipse import EllipseROIManager
from .scalebar import ScaleBarManager, ScaleBarDialog

pg = None  # imported in main() after QApplication is created


def _vertical_separator() -> QtWidgets.QFrame:
    """Thin vertical rule for the top-bar between tool groups."""
    line = QtWidgets.QFrame()
    line.setFrameShape(QtWidgets.QFrame.VLine)
    line.setFrameShadow(QtWidgets.QFrame.Sunken)
    return line


# scipy is optional — filters degrade gracefully if it's not importable.
try:
    from scipy import ndimage as _sp_ndimage  # noqa: F401
    _HAS_SCIPY = True
except Exception:
    _HAS_SCIPY = False

# tifffile / imageio: TIFF export — try both, keep whatever's available.
try:
    import tifffile as _tifffile  # noqa: F401
    _TIFF_BACKEND = "tifffile"
except Exception:
    try:
        import imageio.v3 as _imageio  # noqa: F401
        _TIFF_BACKEND = "imageio"
    except Exception:
        _TIFF_BACKEND = None


def _ensure_pyqtgraph():
    """Import pyqtgraph lazily. QApplication is expected to already exist
    (either created by pystream itself, or by this module's main() when run
    standalone), so importing here is safe."""
    global pg
    if pg is None:
        import pyqtgraph as _pg
        pg = _pg
        pg.setConfigOptions(imageAxisOrder='row-major')
    return pg


class Hdf5MetadataReader:
    """
    Metadata reader from meta-cli project
    Reads metadata from HDF5 datasets (not attributes)
    """
    def __init__(self, filePath, excludedSections=['exchange', 'defaults'], readOnOpen=True):
        self.file = h5py.File(filePath, 'r')
        self.metadataDict = {}
        self.excludedSections = excludedSections
        if readOnOpen:
            self.readMetadata()
    
    def readMetadata(self):
        self.file.visititems(self.__readMetadata)
        return self.metadataDict
    
    def getMetadata(self):
        return self.metadataDict
    
    def __readMetadata(self, name, obj):
        if isinstance(obj, h5py.Dataset):
            rootName = name.split('/')[0]
            if rootName not in self.excludedSections:
                try:
                    # This is when the obj shape is (1,) (DESY, APS)
                    if obj[()].shape[0] == 1:
                        value = obj[()][0]
                        if isinstance(value, bytes):
                            value = value.decode("utf-8", errors='ignore')
                        elif (value.dtype.kind == 'S'):
                            value = value.decode(encoding="utf-8")
                        attr = obj.attrs.get('units')
                        if attr != None:
                            attr = attr.decode('UTF-8')
                        self.metadataDict.update({obj.name: [value, attr]})
                except AttributeError:  # This is when the obj is byte so has no attribute 'shape'
                    value = obj[()]
                    if isinstance(value, bytes):
                        value = value.decode("utf-8", errors='ignore')
                    attr = obj.attrs.get('units')
                    if attr != None:
                        attr = attr.decode('UTF-8')
                    self.metadataDict.update({obj.name: [value, attr]})
                except IndexError:  # This is when the obj shape is () (ESRF and DLS) instead of (1,) (DESY, APS)
                    attr = obj.attrs.get('units')
                    if attr != None:
                        if isinstance(attr, str):
                            pass
                        else:
                            attr = attr.decode('UTF-8')
                    value = obj[()]
                    self.metadataDict.update({obj.name: [value, attr]})
    
    def close(self):
        if self.file:
            self.file.close()
            self.file = None


class MetadataExtractor:
    """Extract metadata from HDF5 files using meta-cli approach"""
    
    @staticmethod
    def extract_metadata(h5file):
        """
        Extract metadata from HDF5 file using Hdf5MetadataReader
        Returns a list of tuples: (full_path, value_with_units, dtype)
        """
        metadata = []
        
        # Use the meta-cli reader approach
        # We need to create a temporary reader that uses the already-open file
        temp_reader = Hdf5MetadataReader.__new__(Hdf5MetadataReader)
        temp_reader.file = h5file
        temp_reader.metadataDict = {}
        temp_reader.excludedSections = ['exchange', 'defaults']
        temp_reader.readMetadata()
        
        meta_dict = temp_reader.getMetadata()
        
        # Convert to list format for table display
        for path, (value, units) in meta_dict.items():
            # Format value with units if available
            if units is not None and units != '':
                value_str = f"{value} {units}"
            else:
                value_str = str(value)
            
            # Get dtype
            dtype = type(value).__name__
            if isinstance(value, np.ndarray):
                dtype = f"ndarray({value.dtype})"
            elif isinstance(value, (np.integer, np.floating)):
                dtype = str(value.dtype)
            
            metadata.append((path, value_str, dtype))
        
        return metadata
    
    @staticmethod
    def extract_tree_structure(h5file):
        """
        Extract the tree structure of the HDF5 file
        Returns a list of tuples: (path, type, shape, dtype)
        """
        structure = []
        
        def visit_item(name, obj):
            if isinstance(obj, h5py.Dataset):
                structure.append((name, 'Dataset', obj.shape, obj.dtype))
            elif isinstance(obj, h5py.Group):
                structure.append((name, 'Group', None, None))
        
        h5file.visititems(visit_item)
        return structure


class MetadataViewer(QtWidgets.QWidget):
    """Widget for displaying HDF5 metadata in a table format"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
    
    def _build_ui(self):
        """Build the metadata viewer interface"""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(10)
        
        # Create tab widget for different views
        self.tab_widget = QtWidgets.QTabWidget()
        
        # Tab 1: Attributes/Metadata
        metadata_widget = QtWidgets.QWidget()
        metadata_layout = QtWidgets.QVBoxLayout(metadata_widget)
        
        # Filter controls
        filter_layout = QtWidgets.QHBoxLayout()
        filter_layout.addWidget(QtWidgets.QLabel("Filter:"))
        
        self.filter_input = QtWidgets.QLineEdit()
        self.filter_input.setPlaceholderText("Type to filter by path or attribute name...")
        self.filter_input.textChanged.connect(self._filter_metadata)
        filter_layout.addWidget(self.filter_input)
        
        metadata_layout.addLayout(filter_layout)
        
        # Metadata table
        self.metadata_table = QtWidgets.QTableWidget()
        self.metadata_table.setColumnCount(3)
        self.metadata_table.setHorizontalHeaderLabels(['Path/Attribute', 'Value', 'Type'])
        self.metadata_table.horizontalHeader().setStretchLastSection(False)
        self.metadata_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.metadata_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Interactive)
        self.metadata_table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self.metadata_table.setAlternatingRowColors(False)  # Disabled for better readability
        self.metadata_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.metadata_table.setSortingEnabled(True)
        metadata_layout.addWidget(self.metadata_table)
        
        # Export button
        export_btn = QtWidgets.QPushButton("Export Metadata to CSV")
        export_btn.clicked.connect(self._export_metadata)
        metadata_layout.addWidget(export_btn)
        
        self.tab_widget.addTab(metadata_widget, "Attributes")
        
        # Tab 2: File Structure
        structure_widget = QtWidgets.QWidget()
        structure_layout = QtWidgets.QVBoxLayout(structure_widget)
        
        # Structure tree
        self.structure_tree = QtWidgets.QTreeWidget()
        self.structure_tree.setHeaderLabels(['Path', 'Type', 'Shape', 'Dtype'])
        self.structure_tree.setAlternatingRowColors(True)
        structure_layout.addWidget(self.structure_tree)
        
        self.tab_widget.addTab(structure_widget, "File Structure")
        
        layout.addWidget(self.tab_widget)
        
        # Status label
        self.status_label = QtWidgets.QLabel("No metadata loaded")
        self.status_label.setStyleSheet("color: #999; padding: 5px;")
        layout.addWidget(self.status_label)
    
    def load_metadata(self, h5file):
        """Load and display metadata from HDF5 file"""
        try:
            # Extract metadata
            metadata = MetadataExtractor.extract_metadata(h5file)
            self._all_metadata = metadata  # Store for filtering
            
            # Populate table
            self._populate_metadata_table(metadata)
            
            # Extract and display structure
            structure = MetadataExtractor.extract_tree_structure(h5file)
            self._populate_structure_tree(h5file, structure)
            
            # Update status
            self.status_label.setText(f"Loaded {len(metadata)} attributes from {len(structure)} objects")
            self.status_label.setStyleSheet("color: #4a4; padding: 5px;")
            
        except Exception as e:
            self.status_label.setText(f"Error loading metadata: {str(e)}")
            self.status_label.setStyleSheet("color: #f44; padding: 5px;")
    
    def _populate_metadata_table(self, metadata):
        """Populate the metadata table with data"""
        self.metadata_table.setSortingEnabled(False)
        self.metadata_table.setRowCount(len(metadata))

        for row, (full_path, value, dtype) in enumerate(metadata):
            path_item = QtWidgets.QTableWidgetItem(full_path)
            path_item.setFlags(path_item.flags() & ~QtCore.Qt.ItemIsEditable)
            self.metadata_table.setItem(row, 0, path_item)

            if isinstance(value, (int, np.integer)):
                value_str = str(value)
            elif isinstance(value, (float, np.floating)):
                value_str = f"{value:.6g}"
            elif isinstance(value, list):
                if len(str(value)) > 500:
                    value_str = str(value)[:500] + "..."
                else:
                    value_str = str(value)
            else:
                value_str = str(value)
                if len(value_str) > 500:
                    value_str = value_str[:500] + "..."

            value_item = QtWidgets.QTableWidgetItem(value_str)
            value_item.setFlags(value_item.flags() & ~QtCore.Qt.ItemIsEditable)
            value_item.setToolTip(str(value))
            self.metadata_table.setItem(row, 1, value_item)

            type_item = QtWidgets.QTableWidgetItem(dtype)
            type_item.setFlags(type_item.flags() & ~QtCore.Qt.ItemIsEditable)
            self.metadata_table.setItem(row, 2, type_item)

        self.metadata_table.setSortingEnabled(True)
        self.metadata_table.resizeColumnsToContents()
        current_width = self.metadata_table.columnWidth(1)
        self.metadata_table.setColumnWidth(1, max(200, current_width))
    
    def _populate_structure_tree(self, h5file, structure):
        """Populate the structure tree with file hierarchy"""
        self.structure_tree.clear()

        root = QtWidgets.QTreeWidgetItem(self.structure_tree)
        root.setText(0, '/')
        root.setText(1, 'Group')
        root.setExpanded(True)

        items_dict = {'/': root}

        for path, obj_type, shape, dtype in sorted(structure):
            parent_path = '/' + '/'.join(path.split('/')[:-1]) if '/' in path else '/'
            parent_path = parent_path.replace('//', '/')

            item = QtWidgets.QTreeWidgetItem()
            item.setText(0, path)
            item.setText(1, obj_type)

            if shape is not None:
                item.setText(2, str(shape))
            if dtype is not None:
                item.setText(3, str(dtype))

            if parent_path in items_dict:
                items_dict[parent_path].addChild(item)
            else:
                root.addChild(item)

            items_dict[path] = item

        self.structure_tree.expandAll()
        self.structure_tree.resizeColumnToContents(0)
        self.structure_tree.resizeColumnToContents(1)
    
    def _filter_metadata(self, text):
        """Filter metadata table by search text"""
        if not hasattr(self, '_all_metadata'):
            return

        if not text:
            self._populate_metadata_table(self._all_metadata)
        else:
            filtered = [
                item for item in self._all_metadata
                if text.lower() in item[0].lower()
            ]
            self._populate_metadata_table(filtered)
    
    def _export_metadata(self):
        """Export metadata to CSV file"""
        if not hasattr(self, '_all_metadata') or not self._all_metadata:
            QtWidgets.QMessageBox.warning(self, "No Data", "No metadata to export")
            return
        
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export Metadata", "", "CSV Files (*.csv)"
        )
        
        if filename:
            try:
                import csv
                with open(filename, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(['Path/Attribute', 'Value', 'Type'])
                    writer.writerows(self._all_metadata)
                
                QtWidgets.QMessageBox.information(
                    self, "Success", f"Metadata exported to {filename}"
                )
            except Exception as e:
                QtWidgets.QMessageBox.critical(
                    self, "Error", f"Failed to export metadata: {str(e)}"
                )
    
    def clear(self):
        """Clear all metadata"""
        self.metadata_table.setRowCount(0)
        self.structure_tree.clear()
        self.status_label.setText("No metadata loaded")
        self.status_label.setStyleSheet("color: #999; padding: 5px;")


class HDF5ImageDividerDialog(QtWidgets.QDialog):
    """Dialog for viewing HDF5 image division with real-time shifting and metadata"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        _ensure_pyqtgraph()
        self.hdf5_file = None
        self.data_dataset = None
        self.data_white_dataset = None

        # Current state
        self.current_index = 0
        self.shift_x = 0
        self.shift_y = 0
        self.normalization_enabled = True
        self.last_directory = ""  # Remember last directory for file dialog
        # ±N frame averaging window (0 = single slice, N > 0 → mean of
        # data[i-N:i+N+1]). Applied BEFORE the data/white division.
        self.avg_n = 0
        # Filter kind + parameter, applied to the displayed image only.
        self.filter_kind = "None"
        self.filter_param = 3.0

        # Cached images
        self.current_data = None
        self.current_white = None
        self.result_image = None

        # Tool managers — attached to self.image_view once it's built.
        self.line_manager = None
        self.roi_manager = None
        self.ellipse_manager = None
        self.scalebar_manager = None
        self.scalebar_dialog = None

        self.setWindowTitle("HDF5 Image Divider with Metadata Viewer")
        self.setModal(False)
        self.resize(1600, 900)
        # Enable drag-and-drop of .h5/.hdf5 files onto the window.
        self.setAcceptDrops(True)

        self._build_ui()
    
    def _build_ui(self):
        """Build the user interface"""
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setSpacing(10)
        
        # Create main tab widget
        self.main_tabs = QtWidgets.QTabWidget()
        
        # Tab 1: Image Viewer
        image_tab = QtWidgets.QWidget()
        self._build_image_tab(image_tab)
        self.main_tabs.addTab(image_tab, "Image Viewer")
        
        # Tab 2: Metadata Viewer
        self.metadata_viewer = MetadataViewer()
        self.main_tabs.addTab(self.metadata_viewer, "Metadata")
        
        main_layout.addWidget(self.main_tabs)
    
    def _build_image_tab(self, parent):
        """Build the image viewer tab. Layout is:

            ┌─────────────────────────────────────────────────────────┐
            │  top_bar: [ Tools ]  [ Filter ]  [ Export ]              │
            ├──────────┬──────────────────────────────────────────────┤
            │ left     │                                              │
            │ panel:   │  right panel: pyqtgraph ImageView            │
            │ file /   │                                              │
            │ index /  │                                              │
            │ contrast │                                              │
            │ / shift  │                                              │
            │ / stats  │                                              │
            └──────────┴──────────────────────────────────────────────┘

        Tools/Filter/Export live in a horizontal top bar so the left
        controls column doesn't stretch tall enough to shrink the image.
        """
        outer = QtWidgets.QVBoxLayout(parent)
        outer.setSpacing(6)

        # Top bar container (populated later once its subgroups exist).
        top_bar = QtWidgets.QWidget()
        self._top_bar_layout = QtWidgets.QHBoxLayout(top_bar)
        self._top_bar_layout.setContentsMargins(0, 0, 0, 0)
        self._top_bar_layout.setSpacing(8)
        outer.addWidget(top_bar)

        # Below the top bar: original two-column split.
        layout = QtWidgets.QHBoxLayout()
        layout.setSpacing(10)
        outer.addLayout(layout, stretch=1)

        # Left panel - Controls
        left_panel = QtWidgets.QWidget()
        left_panel.setMaximumWidth(350)
        control_layout = QtWidgets.QVBoxLayout(left_panel)
        control_layout.setSpacing(10)
        
        # Title
        title = QtWidgets.QLabel("HDF5 Image Division Tool")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        control_layout.addWidget(title)
        
        # File selection group
        file_group = QtWidgets.QGroupBox("File Selection")
        file_layout = QtWidgets.QVBoxLayout()
        
        self.file_path_label = QtWidgets.QLabel("No file loaded")
        self.file_path_label.setWordWrap(True)
        self.file_path_label.setStyleSheet("color: #999;")
        file_layout.addWidget(self.file_path_label)
        
        load_btn = QtWidgets.QPushButton("Load HDF5 File")
        load_btn.clicked.connect(self._load_file)
        file_layout.addWidget(load_btn)
        
        file_group.setLayout(file_layout)
        control_layout.addWidget(file_group)
        
        # Dataset info group
        info_group = QtWidgets.QGroupBox("Dataset Information")
        info_layout = QtWidgets.QFormLayout()
        
        self.data_shape_label = QtWidgets.QLabel("N/A")
        self.white_shape_label = QtWidgets.QLabel("N/A")
        self.num_images_label = QtWidgets.QLabel("N/A")
        
        info_layout.addRow("Data shape:", self.data_shape_label)
        info_layout.addRow("White shape:", self.white_shape_label)
        info_layout.addRow("Number of images:", self.num_images_label)
        
        info_group.setLayout(info_layout)
        control_layout.addWidget(info_group)
        
        # Image selection group
        selection_group = QtWidgets.QGroupBox("Image Selection")
        selection_layout = QtWidgets.QVBoxLayout()
        
        # Slider for image index
        slider_layout = QtWidgets.QHBoxLayout()
        slider_layout.addWidget(QtWidgets.QLabel("Image Index:"))
        
        self.index_label = QtWidgets.QLabel("0")
        self.index_label.setMinimumWidth(50)
        self.index_label.setStyleSheet("font-weight: bold;")
        slider_layout.addWidget(self.index_label)
        
        selection_layout.addLayout(slider_layout)
        
        self.image_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.image_slider.setMinimum(0)
        self.image_slider.setMaximum(0)
        self.image_slider.setValue(0)
        self.image_slider.setEnabled(False)
        self.image_slider.valueChanged.connect(self._on_slider_changed)
        selection_layout.addWidget(self.image_slider)

        # Frame averaging: ±N slices around the current index. 0 = single
        # slice (default). Averages before the data/white division.
        avg_layout = QtWidgets.QHBoxLayout()
        avg_layout.addWidget(QtWidgets.QLabel("Average ±N frames:"))
        self.avg_spin = QtWidgets.QSpinBox()
        self.avg_spin.setRange(0, 500)
        self.avg_spin.setValue(0)
        self.avg_spin.setToolTip(
            "Show the mean of frames [i-N, i+N]. 0 = single slice.\n"
            "Averaging happens BEFORE the data/white division.")
        self.avg_spin.valueChanged.connect(self._on_avg_n_changed)
        avg_layout.addWidget(self.avg_spin)
        selection_layout.addLayout(avg_layout)

        selection_group.setLayout(selection_layout)
        control_layout.addWidget(selection_group)
        
        # Normalization control group
        norm_group = QtWidgets.QGroupBox("Normalization")
        norm_layout = QtWidgets.QVBoxLayout()
        
        self.normalization_checkbox = QtWidgets.QCheckBox("Enable Normalization (data / data_white)")
        self.normalization_checkbox.setChecked(True)
        self.normalization_checkbox.stateChanged.connect(self._on_normalization_changed)
        norm_layout.addWidget(self.normalization_checkbox)
        
        self.mode_label = QtWidgets.QLabel("Mode: <b>Division</b>")
        self.mode_label.setStyleSheet("padding: 5px; background-color: #2a2a2a; border-radius: 3px;")
        norm_layout.addWidget(self.mode_label)
        
        norm_group.setLayout(norm_layout)
        control_layout.addWidget(norm_group)
        
        # Contrast/Histogram control group
        contrast_group = QtWidgets.QGroupBox("Contrast Control")
        contrast_layout = QtWidgets.QVBoxLayout()
        
        # Auto-level options
        auto_layout = QtWidgets.QHBoxLayout()
        auto_layout.addWidget(QtWidgets.QLabel("Auto Level:"))
        
        self.auto_level_combo = QtWidgets.QComboBox()
        self.auto_level_combo.addItems([
            "Per Image (default)",
            "Min/Max", 
            "Percentile 1-99%",
            "Percentile 2-98%",
            "Percentile 5-95%",
            "Manual"
        ])
        self.auto_level_combo.currentIndexChanged.connect(self._on_contrast_changed)
        auto_layout.addWidget(self.auto_level_combo)
        contrast_layout.addLayout(auto_layout)
        
        # Manual controls (initially hidden)
        manual_widget = QtWidgets.QWidget()
        manual_layout = QtWidgets.QFormLayout()
        manual_layout.setContentsMargins(0, 0, 0, 0)
        
        self.min_spin = QtWidgets.QDoubleSpinBox()
        self.min_spin.setRange(-1e10, 1e10)
        self.min_spin.setDecimals(4)
        self.min_spin.setValue(0.0)
        self.min_spin.valueChanged.connect(self._on_manual_levels_changed)
        manual_layout.addRow("Min:", self.min_spin)
        
        self.max_spin = QtWidgets.QDoubleSpinBox()
        self.max_spin.setRange(-1e10, 1e10)
        self.max_spin.setDecimals(4)
        self.max_spin.setValue(1.0)
        self.max_spin.valueChanged.connect(self._on_manual_levels_changed)
        manual_layout.addRow("Max:", self.max_spin)
        
        manual_widget.setLayout(manual_layout)
        manual_widget.setVisible(False)
        self.manual_controls = manual_widget
        contrast_layout.addWidget(manual_widget)
        
        # Reset button
        reset_contrast_btn = QtWidgets.QPushButton("Auto Adjust Now")
        reset_contrast_btn.clicked.connect(self._auto_adjust_contrast)
        contrast_layout.addWidget(reset_contrast_btn)
        
        contrast_group.setLayout(contrast_layout)
        control_layout.addWidget(contrast_group)
        
        # Shift control group
        shift_group = QtWidgets.QGroupBox("Shift Control")
        shift_layout = QtWidgets.QFormLayout()
        
        self.shift_x_label = QtWidgets.QLabel("0")
        self.shift_x_label.setStyleSheet("font-weight: bold;")
        shift_layout.addRow("X Shift (pixels):", self.shift_x_label)
        
        self.shift_y_label = QtWidgets.QLabel("0")
        self.shift_y_label.setStyleSheet("font-weight: bold;")
        shift_layout.addRow("Y Shift (pixels):", self.shift_y_label)
        
        # Reset button
        reset_btn = QtWidgets.QPushButton("Reset Shift")
        reset_btn.clicked.connect(self._reset_shift)
        shift_layout.addRow("", reset_btn)
        
        # Instructions
        self.shift_instructions = QtWidgets.QLabel(
            "<b>Keyboard Controls:</b><br>"
            "← → ↑ ↓: Shift image by 1 pixel<br>"
            "Shift + arrows: Shift by 10 pixels<br>"
            "Ctrl + arrows: Shift by 50 pixels"
        )
        self.shift_instructions.setWordWrap(True)
        self.shift_instructions.setStyleSheet("padding: 10px; background-color: #2a2a2a; border-radius: 5px;")
        shift_layout.addRow(self.shift_instructions)
        
        shift_group.setLayout(shift_layout)
        control_layout.addWidget(shift_group)
        
        # Statistics group
        stats_group = QtWidgets.QGroupBox("Image Statistics")
        stats_layout = QtWidgets.QFormLayout()

        self.min_val_label = QtWidgets.QLabel("N/A")
        self.max_val_label = QtWidgets.QLabel("N/A")
        self.mean_val_label = QtWidgets.QLabel("N/A")
        self.std_val_label = QtWidgets.QLabel("N/A")

        stats_layout.addRow("Min:", self.min_val_label)
        stats_layout.addRow("Max:", self.max_val_label)
        stats_layout.addRow("Mean:", self.mean_val_label)
        stats_layout.addRow("Std Dev:", self.std_val_label)

        stats_group.setLayout(stats_layout)
        control_layout.addWidget(stats_group)

        # Stat labels for the tools live in the LEFT panel (they can get
        # multi-line long — "Length: 234 px | 179.3 µm | ΔX: … ΔY: …") so
        # they don't crowd the top bar. Grouped under an "Analysis"
        # box below Image Statistics.
        analysis_group = QtWidgets.QGroupBox("Analysis")
        analysis_layout = QtWidgets.QVBoxLayout()
        self.lbl_line_info = QtWidgets.QLabel("No line")
        self.lbl_line_info.setStyleSheet("font-size: 9px; color: #ccc;")
        self.lbl_line_info.setWordWrap(True)
        analysis_layout.addWidget(self.lbl_line_info)
        self.lbl_roi_info = QtWidgets.QLabel("No ROI")
        self.lbl_roi_info.setStyleSheet("font-size: 9px; color: #ccc;")
        self.lbl_roi_info.setWordWrap(True)
        analysis_layout.addWidget(self.lbl_roi_info)
        self.lbl_ellipse_info = QtWidgets.QLabel("No ellipse ROI")
        self.lbl_ellipse_info.setStyleSheet("font-size: 9px; color: #ccc;")
        self.lbl_ellipse_info.setWordWrap(True)
        analysis_layout.addWidget(self.lbl_ellipse_info)
        analysis_group.setLayout(analysis_layout)
        control_layout.addWidget(analysis_group)

        # ── TOP BAR: Tools ▾  Filter ▾  Export ▾  (dropdown menus) ────
        # Three compact dropdowns. Same shape as the beamline toolbar.
        # Actions inside each menu do the same thing the removed
        # checkboxes/buttons used to do — no behavior change.

        self._top_bar_layout.addWidget(self._build_tools_menu_button())
        self._top_bar_layout.addWidget(self._build_filter_menu_button())
        self._top_bar_layout.addWidget(self._build_export_menu_button())
        self._top_bar_layout.addStretch(1)

        control_layout.addStretch()

        layout.addWidget(left_panel)
        
        # Right panel - Image display
        right_panel = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # PyQtGraph ImageView
        self.image_view = pg.ImageView()
        self.image_view.ui.roiBtn.hide()
        self.image_view.ui.menuBtn.hide()
        right_layout.addWidget(self.image_view)

        layout.addWidget(right_panel)
        layout.setStretch(1, 1)

        # ── Attach tool managers now that image_view exists ─────────
        # Same manager classes as the live viewer — coord-anchored to the
        # ImageItem, orphan-safe, decimation-aware (display_bin=1 here).
        self.scalebar_manager = ScaleBarManager(
            self.image_view, logger=None, pixel_size=1.0, unit="µm")
        self.line_manager = LineProfileManager(
            self.image_view, self.lbl_line_info, logger=None)
        self.line_manager.set_scalebar_manager(self.scalebar_manager)
        self.roi_manager = ROIManager(
            self.image_view, self.lbl_roi_info, logger=None)
        self.ellipse_manager = EllipseROIManager(
            self.image_view, self.lbl_ellipse_info, logger=None)

        # Wire the checkable menu actions into the four managers.
        # Managers' toggle() expects a Qt.CheckState value, not a bool,
        # so we translate. QAction.toggled(bool) fires only on the
        # user-driven check/uncheck.
        def _toggle(mgr):
            def _cb(checked):
                mgr.toggle(QtCore.Qt.Checked if checked
                           else QtCore.Qt.Unchecked)
            return _cb
        self.act_line.toggled.connect(_toggle(self.line_manager))
        self.act_roi.toggled.connect(_toggle(self.roi_manager))
        self.act_ellipse.toggled.connect(_toggle(self.ellipse_manager))
        self.act_scalebar.toggled.connect(_toggle(self.scalebar_manager))
    
    def _load_file(self):
        """Open a file dialog and route the chosen path through
        `_load_specific_file`. Drag-and-drop uses the same load method."""
        start_dir = self.last_directory if self.last_directory else os.path.expanduser("~")
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open HDF5 File", start_dir,
            "HDF5 Files (*.h5 *.hdf5);;All Files (*)"
        )
        if not filename:
            return
        self._load_specific_file(filename)

    # Datasets we recognize as "the volume", tried in this order.
    # First hit wins. Standard raw-tomo files use `exchange/data`;
    # tomocupy / tomogui reconstruction output uses `exchange/data`
    # too but sometimes `exchange/recon` or `reconstruction`; a plain
    # HDF5 stack may just live at `/data`.
    _DATA_DATASET_CANDIDATES = (
        "exchange/data",
        "exchange/recon",
        "reconstruction",
        "data",
    )

    @staticmethod
    def _first_present_3d(hdf5_file, paths):
        """Return the (path, dataset) of the first path in `paths` that
        exists in the file AND is a 3+D dataset. None if no match."""
        for p in paths:
            if p in hdf5_file:
                obj = hdf5_file[p]
                if isinstance(obj, h5py.Dataset) and len(obj.shape) >= 3:
                    return p, obj
        return None, None

    def _load_specific_file(self, filename: str):
        """Open `filename` as an HDF5 file and populate the viewer.
        Auto-detects two modes:

          * **Raw tomo** — `exchange/data` + `exchange/data_white` both
            present. The viewer runs its original path: normalize
            (data / white), let the user shift the white, etc.
          * **Reconstruction / generic** — a recognized 3D dataset is
            present but no white-field companion. The viewer switches
            to slice-view mode: division is disabled, the white-shape
            row shows "(no flats)", and the slider walks slices of
            the volume directly. Handles tomogui / tomocupy `_rec.h5`
            output (dataset `/exchange/data` or `/exchange/recon`)
            plus any other standard HDF5 stack under `/data`.

        Called by the file dialog, drag-and-drop, and any future
        programmatic caller."""
        if not filename:
            return
        self.last_directory = os.path.dirname(filename)
        try:
            if self.hdf5_file is not None:
                self.hdf5_file.close()

            self.hdf5_file = h5py.File(filename, 'r')

            data_path, data_dset = self._first_present_3d(
                self.hdf5_file, self._DATA_DATASET_CANDIDATES)
            if data_dset is None:
                QtWidgets.QMessageBox.warning(
                    self, "Unrecognized File Structure",
                    "Couldn't find a 3D dataset at any of the known paths:\n"
                    "  - " + "\n  - ".join(self._DATA_DATASET_CANDIDATES)
                    + "\n\nUse the Metadata tab to inspect the file's tree."
                )
                # Still show metadata so the user can figure out what's there.
                self.metadata_viewer.load_metadata(self.hdf5_file)
                return

            self.data_dataset = data_dset

            # White-field is optional. Present → raw-tomo mode (division
            # enabled). Absent → recon / generic mode (slice viewer,
            # division disabled).
            if 'exchange/data_white' in self.hdf5_file:
                self.data_white_dataset = self.hdf5_file['exchange/data_white']
                self._enter_raw_mode()
            else:
                self.data_white_dataset = None
                self._enter_recon_mode(dataset_path=data_path)

            self.file_path_label.setText(os.path.basename(filename))
            self.file_path_label.setStyleSheet("color: white;")
            self.file_path_label.setToolTip(filename)

            self.data_shape_label.setText(str(self.data_dataset.shape))

            num_images = self.data_dataset.shape[0]
            self.num_images_label.setText(str(num_images))

            self.image_slider.setMaximum(num_images - 1)
            self.image_slider.setEnabled(True)

            self._load_and_display_image(0)

            self.metadata_viewer.load_metadata(self.hdf5_file)

        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Failed to load file:\n{str(e)}"
            )
            if self.hdf5_file is not None:
                self.hdf5_file.close()
                self.hdf5_file = None

    # ── Mode switching (raw tomo vs recon / generic slice viewer) ──

    def _enter_raw_mode(self):
        """Restore full raw-tomo UI — division on, white-shape shown,
        normalization checkbox active."""
        self.is_recon_mode = False
        self.white_shape_label.setText(str(self.data_white_dataset.shape))
        self.normalization_checkbox.setEnabled(True)
        self.normalization_checkbox.setChecked(True)
        # White-field shifting only makes sense with a white present.
        if hasattr(self, "shift_x_slider"):
            self.shift_x_slider.setEnabled(True)
        if hasattr(self, "shift_y_slider"):
            self.shift_y_slider.setEnabled(True)

    def _enter_recon_mode(self, dataset_path: str):
        """Slice viewer for reconstruction / generic 3D volumes: no
        white, no division, no white-shifting. Grey out anything that
        needs a white-field to make sense."""
        self.is_recon_mode = True
        self.white_shape_label.setText(f"(no flats — slice view of /{dataset_path})")
        self.normalization_enabled = False
        self.normalization_checkbox.setChecked(False)
        self.normalization_checkbox.setEnabled(False)
        if hasattr(self, "shift_x_slider"):
            self.shift_x_slider.setEnabled(False)
        if hasattr(self, "shift_y_slider"):
            self.shift_y_slider.setEnabled(False)

    # ── Drag-and-drop ────────────────────────────────────────────────
    @staticmethod
    def _urls_to_hdf5_paths(mime):
        """Return the list of local .h5 / .hdf5 paths inside a mime object.
        Ignores non-file URLs and other extensions."""
        paths = []
        if not mime.hasUrls():
            return paths
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            p = url.toLocalFile()
            if p.lower().endswith((".h5", ".hdf5")):
                paths.append(p)
        return paths

    def dragEnterEvent(self, event):
        if self._urls_to_hdf5_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        # Needed on some platforms to keep the drag cursor showing "accept".
        if self._urls_to_hdf5_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths = self._urls_to_hdf5_paths(event.mimeData())
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        # If several files dropped, take the first — mirrors most viewer
        # conventions (Preview.app, Fiji, etc.).
        self._load_specific_file(paths[0])
    
    def _load_and_display_image(self, index):
        """Load and display image at given index. When `self.avg_n > 0`
        loads the ±N-frame window and averages along axis 0 before the
        data/white division. In recon mode there's no white — the
        current_white/shift/division steps are skipped entirely and
        `current_data` is displayed as a raw slice."""
        if self.data_dataset is None:
            return

        try:
            self.current_index = index
            self.index_label.setText(str(index))

            n_frames_total = self.data_dataset.shape[0]

            # Load current_data (with optional ±N averaging).
            if self.avg_n > 0:
                lo = max(0, index - self.avg_n)
                hi = min(n_frames_total, index + self.avg_n + 1)
                # h5py sliced read — only pulls the frames we need.
                self.current_data = np.array(
                    self.data_dataset[lo:hi], dtype=np.float32
                ).mean(axis=0)
            else:
                self.current_data = np.array(self.data_dataset[index])

            # White-field load — only in raw-tomo mode.
            if getattr(self, "is_recon_mode", False) or self.data_white_dataset is None:
                self.current_white = None
            else:
                n_whites_total = self.data_white_dataset.shape[0]
                if self.avg_n > 0:
                    lo = max(0, index - self.avg_n)
                    hi = min(n_frames_total, index + self.avg_n + 1)
                    if n_whites_total > 1:
                        wlo = max(0, min(lo, n_whites_total - 1))
                        whi = max(wlo + 1, min(hi, n_whites_total))
                        self.current_white = np.array(
                            self.data_white_dataset[wlo:whi], dtype=np.float32
                        ).mean(axis=0)
                    else:
                        self.current_white = np.array(
                            self.data_white_dataset[0], dtype=np.float32)
                else:
                    white_index = min(index, n_whites_total - 1)
                    self.current_white = np.array(
                        self.data_white_dataset[white_index])

            self._update_display()

        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Failed to load image:\n{str(e)}"
            )
    
    def _update_display(self):
        """Update the image display with current shift, normalization,
        and display-only filter settings. Skips division entirely in
        recon mode (no white-field to divide by)."""
        if self.current_data is None:
            return

        try:
            if self.normalization_enabled and self.current_white is not None:
                shifted_white = self._apply_shift(self.current_white, self.shift_x, self.shift_y)

                epsilon = 1e-10
                self.result_image = self.current_data / (shifted_white + epsilon)

                self.result_image = np.nan_to_num(self.result_image, nan=0.0, posinf=0.0, neginf=0.0)
            else:
                self.result_image = self.current_data.copy()

            # Display-only filter (never touches the on-disk data).
            self.result_image = self._apply_filter(self.result_image)

            self._update_statistics()

            self._apply_contrast_settings()

        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Failed to update display:\n{str(e)}"
            )

    def _apply_filter(self, img):
        """Apply the currently-selected filter to `img`. Display-only:
        the returned array replaces `self.result_image` in the display
        pipeline; the raw dataset is never modified."""
        if not _HAS_SCIPY or self.filter_kind == "None":
            return img
        try:
            if self.filter_kind == "Median":
                k = max(1, int(round(self.filter_param)))
                if k % 2 == 0:
                    k += 1  # scipy wants an odd kernel
                return _sp_ndimage.median_filter(img, size=k)
            if self.filter_kind == "Gaussian":
                sigma = max(0.0, float(self.filter_param))
                if sigma == 0.0:
                    return img
                return _sp_ndimage.gaussian_filter(img, sigma=sigma)
            if self.filter_kind == "Threshold (>)":
                return (img > float(self.filter_param)).astype(np.float32)
        except Exception as e:
            if hasattr(self, "logger") and self.logger:
                self.logger.warning("Filter %s failed: %s", self.filter_kind, e)
        return img
    
    def _apply_contrast_settings(self):
        """Apply contrast/level settings to the image"""
        if self.result_image is None:
            return

        mode_index = self.auto_level_combo.currentIndex()

        if mode_index == 0:  # Per Image (default)
            self.image_view.setImage(self.result_image, autoLevels=True, autoRange=False)
        elif mode_index == 1:  # Min/Max
            vmin, vmax = np.min(self.result_image), np.max(self.result_image)
            self.image_view.setImage(self.result_image, autoLevels=False, autoRange=False,
                                    levels=(vmin, vmax))
        elif mode_index == 2:  # Percentile 1-99%
            vmin, vmax = np.percentile(self.result_image, [1, 99])
            self.image_view.setImage(self.result_image, autoLevels=False, autoRange=False,
                                    levels=(vmin, vmax))
        elif mode_index == 3:  # Percentile 2-98%
            vmin, vmax = np.percentile(self.result_image, [2, 98])
            self.image_view.setImage(self.result_image, autoLevels=False, autoRange=False,
                                    levels=(vmin, vmax))
        elif mode_index == 4:  # Percentile 5-95%
            vmin, vmax = np.percentile(self.result_image, [5, 95])
            self.image_view.setImage(self.result_image, autoLevels=False, autoRange=False,
                                    levels=(vmin, vmax))
        elif mode_index == 5:  # Manual
            vmin = self.min_spin.value()
            vmax = self.max_spin.value()
            self.image_view.setImage(self.result_image, autoLevels=False, autoRange=False,
                                    levels=(vmin, vmax))

        # Fan the fresh displayed image out to the tool managers so ROI
        # stats, line profile, and scale bar all refresh whenever the
        # slice / filter / contrast changes.
        for mgr in (self.line_manager, self.roi_manager, self.ellipse_manager):
            if mgr is not None:
                try:
                    mgr.update_stats(self.result_image)
                except Exception:
                    pass
        if self.scalebar_manager is not None:
            try:
                self.scalebar_manager.update_image(self.result_image)
            except Exception:
                pass
    
    def _update_statistics(self):
        """Update image statistics labels"""
        if self.result_image is None:
            return
        
        self.min_val_label.setText(f"{np.min(self.result_image):.4f}")
        self.max_val_label.setText(f"{np.max(self.result_image):.4f}")
        self.mean_val_label.setText(f"{np.mean(self.result_image):.4f}")
        self.std_val_label.setText(f"{np.std(self.result_image):.4f}")
    
    def _apply_shift(self, image, shift_x, shift_y):
        """Apply x and y shift to an image"""
        if shift_x == 0 and shift_y == 0:
            return image

        shifted = np.zeros_like(image)

        src_x_start = max(0, -shift_x)
        src_x_end = image.shape[1] - max(0, shift_x)
        src_y_start = max(0, -shift_y)
        src_y_end = image.shape[0] - max(0, shift_y)

        dst_x_start = max(0, shift_x)
        dst_x_end = image.shape[1] - max(0, -shift_x)
        dst_y_start = max(0, shift_y)
        dst_y_end = image.shape[0] - max(0, -shift_y)

        shifted[dst_y_start:dst_y_end, dst_x_start:dst_x_end] = \
            image[src_y_start:src_y_end, src_x_start:src_x_end]

        return shifted
    
    def _on_slider_changed(self, value):
        """Handle slider value change"""
        self._load_and_display_image(value)
    
    def _on_normalization_changed(self, state):
        """Handle normalization checkbox change"""
        self.normalization_enabled = (state == QtCore.Qt.Checked)

        if self.normalization_enabled:
            self.mode_label.setText("Mode: <b>Division (data / data_white)</b>")
        else:
            self.mode_label.setText("Mode: <b>Raw Data Only</b>")

        self._update_display()
    
    def _on_contrast_changed(self, index):
        """Handle contrast mode change"""
        is_manual = (index == 5)
        self.manual_controls.setVisible(is_manual)

        if is_manual and self.result_image is not None:
            self.min_spin.setValue(float(np.min(self.result_image)))
            self.max_spin.setValue(float(np.max(self.result_image)))

        self._update_display()
    
    def _on_manual_levels_changed(self):
        """Handle manual level spinbox changes"""
        if self.auto_level_combo.currentIndex() == 5:  # Only if in manual mode
            self._update_display()

    def _auto_adjust_contrast(self):
        """Auto-adjust contrast based on current mode"""
        self._update_display()

    # ── Top-bar dropdown builders ────────────────────────────────────
    def _build_tools_menu_button(self) -> QtWidgets.QToolButton:
        """Tools ▾ — checkable actions for each tool plus reset /
        profile / settings actions. Same behavior as the removed
        checkboxes and buttons."""
        menu = QtWidgets.QMenu(self)

        self.act_line = menu.addAction("Line")
        self.act_line.setCheckable(True)
        self.act_roi = menu.addAction("Rect ROI")
        self.act_roi.setCheckable(True)
        self.act_ellipse = menu.addAction("Ellipse ROI")
        self.act_ellipse.setCheckable(True)
        self.act_scalebar = menu.addAction("Scale bar")
        self.act_scalebar.setCheckable(True)

        menu.addSeparator()

        act_line_profile = menu.addAction("Line: open profile plot…")
        act_line_profile.triggered.connect(
            lambda: self.line_manager.show_profile_dialog()
            if self.line_manager else None)
        act_line_reset = menu.addAction("Line: reset")
        act_line_reset.triggered.connect(
            lambda: self.line_manager.reset() if self.line_manager else None)
        act_roi_reset = menu.addAction("Rect ROI: reset")
        act_roi_reset.triggered.connect(
            lambda: self.roi_manager.reset() if self.roi_manager else None)
        act_ell_reset = menu.addAction("Ellipse ROI: reset")
        act_ell_reset.triggered.connect(
            lambda: self.ellipse_manager.reset() if self.ellipse_manager else None)

        menu.addSeparator()
        act_sb_settings = menu.addAction("Scale bar: settings…")
        act_sb_settings.triggered.connect(self._open_scalebar_settings)

        btn = QtWidgets.QToolButton(self)
        btn.setText("Tools  ▾")
        btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        btn.setMenu(menu)
        btn.setToolTip(
            "Line, ROI, and scale-bar tools.\n"
            "Check to enable, uncheck to remove.")
        return btn

    def _build_filter_menu_button(self) -> QtWidgets.QToolButton:
        """Filter ▾ — radio-check kind + inline spinbox for the param."""
        menu = QtWidgets.QMenu(self)

        # Kind selection as an exclusive group of checkable actions.
        self.filter_action_group = QtWidgets.QActionGroup(menu)
        self.filter_action_group.setExclusive(True)
        self.filter_actions: dict = {}
        for kind in ("None", "Median", "Gaussian", "Threshold (>)"):
            act = menu.addAction(kind)
            act.setCheckable(True)
            act.setActionGroup(self.filter_action_group)
            if kind == "None":
                act.setChecked(True)
            act.triggered.connect(
                lambda _checked, k=kind: self._on_filter_kind_changed(k))
            self.filter_actions[kind] = act

        menu.addSeparator()

        # Param spinbox lives inside the menu as a QWidgetAction.
        param_widget = QtWidgets.QWidget()
        pl = QtWidgets.QHBoxLayout(param_widget)
        pl.setContentsMargins(8, 4, 8, 4)
        pl.addWidget(QtWidgets.QLabel("Param:"))
        self.filter_param_spin = QtWidgets.QDoubleSpinBox()
        self.filter_param_spin.setRange(0.0, 1e6)
        self.filter_param_spin.setDecimals(3)
        self.filter_param_spin.setValue(3.0)
        self.filter_param_spin.setSingleStep(0.5)
        self.filter_param_spin.setToolTip(
            "Median: kernel (odd int, rounded)\n"
            "Gaussian: σ pixels\n"
            "Threshold: cutoff value")
        self.filter_param_spin.valueChanged.connect(self._on_filter_param_changed)
        pl.addWidget(self.filter_param_spin)
        wa = QtWidgets.QWidgetAction(menu)
        wa.setDefaultWidget(param_widget)
        menu.addAction(wa)

        if not _HAS_SCIPY:
            for act in self.filter_actions.values():
                if act.text() != "None":
                    act.setEnabled(False)
            self.filter_param_spin.setEnabled(False)
            menu.addSeparator()
            note = menu.addAction("scipy not installed — filters disabled")
            note.setEnabled(False)

        btn = QtWidgets.QToolButton(self)
        btn.setText("Filter  ▾")
        btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        btn.setMenu(menu)
        btn.setToolTip(
            "Display-only filter applied to the current slice "
            "(does not modify the file).")
        return btn

    def _build_export_menu_button(self) -> QtWidgets.QToolButton:
        """Export ▾ — one action per format, each pops a save dialog
        pre-filtered to that extension."""
        menu = QtWidgets.QMenu(self)
        act_png = menu.addAction("Save as PNG… (rendered view)")
        act_png.triggered.connect(lambda: self._on_save(preferred="png"))
        act_tif = menu.addAction("Save as TIFF… (float32 raw)")
        act_tif.triggered.connect(lambda: self._on_save(preferred="tiff"))
        act_npy = menu.addAction("Save as NPY… (numpy array)")
        act_npy.triggered.connect(lambda: self._on_save(preferred="npy"))
        btn = QtWidgets.QToolButton(self)
        btn.setText("Export  ▾")
        btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        btn.setMenu(menu)
        btn.setToolTip(
            "Save the current view — PNG mirrors what you see "
            "(with overlays), TIFF/NPY save the raw float32.")
        return btn

    # ── Averaging + filter handlers ──────────────────────────────────
    def _on_avg_n_changed(self, value):
        self.avg_n = max(0, int(value))
        # Re-read the current index with the new window size.
        self._load_and_display_image(self.current_index)

    def _on_filter_kind_changed(self, text):
        self.filter_kind = text
        # Nudge the param default to something sensible per kind.
        if text == "Median" and self.filter_param_spin.value() < 3:
            self.filter_param_spin.setValue(3.0)
        elif text == "Gaussian" and self.filter_param_spin.value() > 20:
            self.filter_param_spin.setValue(2.0)
        self._update_display()

    def _on_filter_param_changed(self, value):
        self.filter_param = float(value)
        if self.filter_kind != "None":
            self._update_display()

    # ── Scale bar settings dialog ────────────────────────────────────
    def _open_scalebar_settings(self):
        if self.scalebar_manager is None:
            return
        if self.scalebar_dialog is None:
            self.scalebar_dialog = ScaleBarDialog(self.scalebar_manager, parent=self)
        self.scalebar_dialog.show()
        self.scalebar_dialog.raise_()
        self.scalebar_dialog.activateWindow()

    # ── Save / export ────────────────────────────────────────────────
    def _on_save(self, preferred: str = "png"):
        """Save the current displayed image. `preferred` is one of
        'png' / 'tiff' / 'npy' and only controls which filter appears
        first in the dialog — the user can still pick another."""
        if self.result_image is None:
            QtWidgets.QMessageBox.information(
                self, "Save", "Load a file first — nothing to save.")
            return
        start_dir = self.last_directory if self.last_directory else os.path.expanduser("~")

        png_f = "PNG (*.png)"
        tif_f = "TIFF (*.tif *.tiff)"
        npy_f = "Numpy (*.npy)"
        order = {"png": [png_f, tif_f, npy_f],
                 "tiff": [tif_f, png_f, npy_f],
                 "npy": [npy_f, png_f, tif_f]}.get(preferred, [png_f, tif_f, npy_f])
        filters = ";;".join(order)

        filename, chosen = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save current view", start_dir, filters)
        if not filename:
            return
        try:
            lower = filename.lower()
            if lower.endswith(".png") or "PNG" in chosen:
                # Render the visible ImageView — includes tool overlays.
                from pyqtgraph.exporters import ImageExporter
                exporter = ImageExporter(self.image_view.getImageItem())
                exporter.export(filename)
            elif lower.endswith((".tif", ".tiff")) or "TIFF" in chosen:
                arr = self.result_image.astype(np.float32)
                if _TIFF_BACKEND == "tifffile":
                    _tifffile.imwrite(filename, arr)
                elif _TIFF_BACKEND == "imageio":
                    _imageio.imwrite(filename, arr)
                else:
                    raise RuntimeError(
                        "TIFF export needs `tifffile` or `imageio` — "
                        "neither is installed.")
            elif lower.endswith(".npy") or "Numpy" in chosen:
                np.save(filename, self.result_image.astype(np.float32))
            else:
                # No recognized extension → default to PNG.
                from pyqtgraph.exporters import ImageExporter
                exporter = ImageExporter(self.image_view.getImageItem())
                exporter.export(filename + ".png")
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Save failed", f"Could not save:\n{e}")
    
    def _reset_shift(self):
        """Reset shift to zero"""
        self.shift_x = 0
        self.shift_y = 0
        self._update_shift_labels()
        self._update_display()
    
    def _update_shift_labels(self):
        """Update shift labels"""
        self.shift_x_label.setText(str(self.shift_x))
        self.shift_y_label.setText(str(self.shift_y))
    
    def keyPressEvent(self, event):
        """Handle keyboard events for shifting"""
        if self.current_data is None:
            return

        if not self.normalization_enabled:
            super().keyPressEvent(event)
            return

        step = 1
        if event.modifiers() & QtCore.Qt.ShiftModifier:
            step = 10
        elif event.modifiers() & QtCore.Qt.ControlModifier:
            step = 50

        if event.key() == QtCore.Qt.Key_Left:
            self.shift_x -= step
            self._update_shift_labels()
            self._update_display()
        elif event.key() == QtCore.Qt.Key_Right:
            self.shift_x += step
            self._update_shift_labels()
            self._update_display()
        elif event.key() == QtCore.Qt.Key_Up:
            self.shift_y -= step
            self._update_shift_labels()
            self._update_display()
        elif event.key() == QtCore.Qt.Key_Down:
            self.shift_y += step
            self._update_shift_labels()
            self._update_display()
        else:
            super().keyPressEvent(event)
    
    def closeEvent(self, event):
        """Clean up when closing"""
        # Tear down tool managers first (drops their scene items + any
        # popup dialogs like the line-profile plot).
        for mgr in (self.line_manager, self.roi_manager,
                    self.ellipse_manager, self.scalebar_manager):
            if mgr is not None:
                try:
                    mgr.cleanup()
                except Exception:
                    pass
        try:
            if self.hdf5_file is not None:
                self.hdf5_file.close()
                self.hdf5_file = None
        except Exception as e:
            print(f"Warning: Error closing HDF5 file: {e}")

        # Accept the event immediately to prevent hanging
        event.accept()


# ==================== Standalone Mode ====================
def main():
    """Run the HDF5 image divider as a standalone application"""
    import sys
    global pg

    # QApplication MUST exist before importing pyqtgraph on some versions
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)

    import pyqtgraph as _pg
    pg = _pg
    pg.setConfigOptions(imageAxisOrder='row-major')
    app.setApplicationName("HDF5 Image Divider with Metadata")
    
    # Apply dark theme
    app.setStyle('Fusion')
    palette = QtGui.QPalette()
    
    palette.setColor(QtGui.QPalette.Window, QtGui.QColor(53, 53, 53))
    palette.setColor(QtGui.QPalette.WindowText, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.Base, QtGui.QColor(35, 35, 35))
    palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(53, 53, 53))
    palette.setColor(QtGui.QPalette.Text, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.BrightText, QtCore.Qt.red)
    palette.setColor(QtGui.QPalette.Button, QtGui.QColor(53, 53, 53))
    palette.setColor(QtGui.QPalette.ButtonText, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor(25, 25, 25))
    palette.setColor(QtGui.QPalette.ToolTipText, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor(42, 130, 218))
    palette.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.WindowText, QtGui.QColor(127, 127, 127))
    palette.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.Text, QtGui.QColor(127, 127, 127))
    palette.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.ButtonText, QtGui.QColor(127, 127, 127))
    
    app.setPalette(palette)
    
    app.setStyleSheet("""
        QGroupBox {
            border: 1px solid #555;
            border-radius: 5px;
            margin-top: 10px;
            font-weight: bold;
            padding-top: 10px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px 0 5px;
        }
        QSpinBox, QDoubleSpinBox, QLineEdit {
            background-color: #2a2a2a;
            border: 1px solid #555;
            border-radius: 3px;
            padding: 3px;
            min-height: 20px;
        }
        QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {
            border: 1px solid #2a82da;
        }
        QPushButton {
            background-color: #454545;
            border: 1px solid #666;
            border-radius: 4px;
            padding: 6px 16px;
            min-width: 80px;
        }
        QPushButton:hover {
            background-color: #505050;
            border: 1px solid #888;
        }
        QPushButton:pressed {
            background-color: #3a3a3a;
        }
        QPushButton:disabled {
            background-color: #353535;
            color: #666;
        }
        QSlider::groove:horizontal {
            border: 1px solid #555;
            height: 8px;
            background: #2a2a2a;
            border-radius: 4px;
        }
        QSlider::handle:horizontal {
            background: #2a82da;
            border: 1px solid #3a95d8;
            width: 18px;
            margin: -5px 0;
            border-radius: 9px;
        }
        QSlider::handle:horizontal:hover {
            background: #3a95d8;
        }
        QTableWidget {
            gridline-color: #555;
            selection-background-color: #2a82da;
        }
        QHeaderView::section {
            background-color: #454545;
            padding: 5px;
            border: 1px solid #555;
            font-weight: bold;
        }
        QTabWidget::pane {
            border: 1px solid #555;
            border-radius: 3px;
        }
        QTabBar::tab {
            background-color: #454545;
            border: 1px solid #555;
            padding: 8px 16px;
            margin-right: 2px;
        }
        QTabBar::tab:selected {
            background-color: #2a82da;
        }
        QTabBar::tab:hover {
            background-color: #505050;
        }
    """)
    
    dialog = HDF5ImageDividerDialog()
    dialog.show()
    
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()