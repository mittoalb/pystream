#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Multi-Resolution Zarr Viewer with Dynamic Chunk Loading
--------------------------------------------------------
Neuroglancer-style viewer for multi-resolution Zarr arrays.
Only loads visible chunks at appropriate resolution levels based on zoom.

Expected Zarr structure:
- Multi-scale format (OME-NGFF compatible)
- /0, /1, /2, ... (pyramid levels, 0 = highest resolution)
- Metadata in .zattrs with scale information

Features:
- Dynamic resolution switching based on zoom level
- Chunk-based loading (only visible regions)
- Real-time performance for large datasets
- Metadata viewer
"""

import z5py
import numpy as np
from typing import Optional, List, Tuple
from PyQt5 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg
from pathlib import Path
import json

pg.setConfigOptions(imageAxisOrder='row-major')


class ZarrMetadataExtractor:
    """Extract metadata from Zarr files (z5py compatible)"""
    
    @staticmethod
    def extract_metadata(zarr_group):
        """Extract metadata from Zarr group and arrays"""
        metadata = []
        
        # Get group attributes
        if hasattr(zarr_group, 'attrs'):
            try:
                attrs_dict = dict(zarr_group.attrs)
                for key, value in attrs_dict.items():
                    value_str = json.dumps(value, indent=2) if isinstance(value, (dict, list)) else str(value)
                    if len(value_str) > 500:
                        value_str = value_str[:500] + "..."
                    metadata.append((f"/.zattrs/{key}", value_str, type(value).__name__))
            except:
                pass
        
        # Recursively get array metadata
        def visit_items(name, obj):
            # Check if it's a dataset (z5py uses different API than zarr)
            if hasattr(obj, 'shape') and hasattr(obj, 'dtype'):
                # Array attributes
                if hasattr(obj, 'attrs'):
                    try:
                        attrs_dict = dict(obj.attrs)
                        for key, value in attrs_dict.items():
                            value_str = json.dumps(value, indent=2) if isinstance(value, (dict, list)) else str(value)
                            if len(value_str) > 500:
                                value_str = value_str[:500] + "..."
                            metadata.append((f"/{name}/.zattrs/{key}", value_str, type(value).__name__))
                    except:
                        pass
                
                # Array properties
                metadata.append((f"/{name}/shape", str(obj.shape), "tuple"))
                metadata.append((f"/{name}/dtype", str(obj.dtype), "dtype"))
                if hasattr(obj, 'chunks'):
                    metadata.append((f"/{name}/chunks", str(obj.chunks), "tuple"))
                if hasattr(obj, 'compression'):
                    metadata.append((f"/{name}/compression", str(obj.compression), "str"))
        
        try:
            zarr_group.visititems(visit_items)
        except AttributeError:
            # Fallback for z5py: iterate manually
            for key in zarr_group.keys():
                try:
                    obj = zarr_group[key]
                    visit_items(key, obj)
                except:
                    pass
        
        return metadata
    
    @staticmethod
    def extract_tree_structure(zarr_group):
        """Extract tree structure of Zarr hierarchy"""
        structure = []
        
        def visit_items(name, obj):
            # Check if it's a dataset
            if hasattr(obj, 'shape') and hasattr(obj, 'dtype'):
                structure.append((name, 'Dataset', obj.shape, obj.dtype))
            elif hasattr(obj, 'keys'):  # Group-like
                structure.append((name, 'Group', None, None))
        
        try:
            zarr_group.visititems(visit_items)
        except AttributeError:
            # Fallback for z5py: iterate manually
            for key in zarr_group.keys():
                try:
                    obj = zarr_group[key]
                    visit_items(key, obj)
                except:
                    pass
        
        return structure


class MetadataViewer(QtWidgets.QWidget):
    """Widget for displaying Zarr metadata"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
    
    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        
        # Tab widget
        self.tab_widget = QtWidgets.QTabWidget()
        
        # Attributes tab
        metadata_widget = QtWidgets.QWidget()
        metadata_layout = QtWidgets.QVBoxLayout(metadata_widget)
        
        # Filter
        filter_layout = QtWidgets.QHBoxLayout()
        filter_layout.addWidget(QtWidgets.QLabel("Filter:"))
        self.filter_input = QtWidgets.QLineEdit()
        self.filter_input.setPlaceholderText("Type to filter...")
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
        self.metadata_table.setAlternatingRowColors(True)
        self.metadata_table.setSortingEnabled(True)
        metadata_layout.addWidget(self.metadata_table)
        
        self.tab_widget.addTab(metadata_widget, "Attributes")
        
        # Structure tab
        structure_widget = QtWidgets.QWidget()
        structure_layout = QtWidgets.QVBoxLayout(structure_widget)
        
        self.structure_tree = QtWidgets.QTreeWidget()
        self.structure_tree.setHeaderLabels(['Path', 'Type', 'Shape', 'Dtype'])
        self.structure_tree.setAlternatingRowColors(True)
        structure_layout.addWidget(self.structure_tree)
        
        self.tab_widget.addTab(structure_widget, "Structure")
        
        layout.addWidget(self.tab_widget)
        
        # Status
        self.status_label = QtWidgets.QLabel("No metadata loaded")
        self.status_label.setStyleSheet("color: #999; padding: 5px;")
        layout.addWidget(self.status_label)
    
    def load_metadata(self, zarr_group):
        """Load metadata from Zarr group"""
        try:
            metadata = ZarrMetadataExtractor.extract_metadata(zarr_group)
            self._all_metadata = metadata
            self._populate_metadata_table(metadata)
            
            structure = ZarrMetadataExtractor.extract_tree_structure(zarr_group)
            self._populate_structure_tree(structure)
            
            self.status_label.setText(f"Loaded {len(metadata)} attributes from Zarr store")
            self.status_label.setStyleSheet("color: #4a4; padding: 5px;")
        except Exception as e:
            self.status_label.setText(f"Error: {str(e)}")
            self.status_label.setStyleSheet("color: #f44; padding: 5px;")
    
    def _populate_metadata_table(self, metadata):
        self.metadata_table.setSortingEnabled(False)
        self.metadata_table.setRowCount(len(metadata))
        
        for row, (path, value, dtype) in enumerate(metadata):
            path_item = QtWidgets.QTableWidgetItem(path)
            path_item.setFlags(path_item.flags() & ~QtCore.Qt.ItemIsEditable)
            self.metadata_table.setItem(row, 0, path_item)
            
            value_item = QtWidgets.QTableWidgetItem(str(value))
            value_item.setFlags(value_item.flags() & ~QtCore.Qt.ItemIsEditable)
            value_item.setToolTip(str(value))
            self.metadata_table.setItem(row, 1, value_item)
            
            type_item = QtWidgets.QTableWidgetItem(dtype)
            type_item.setFlags(type_item.flags() & ~QtCore.Qt.ItemIsEditable)
            self.metadata_table.setItem(row, 2, type_item)
        
        self.metadata_table.setSortingEnabled(True)
        self.metadata_table.resizeColumnsToContents()
    
    def _populate_structure_tree(self, structure):
        self.structure_tree.clear()
        root = QtWidgets.QTreeWidgetItem(self.structure_tree)
        root.setText(0, '/')
        root.setText(1, 'Group')
        root.setExpanded(True)
        
        for path, obj_type, shape, dtype in sorted(structure):
            item = QtWidgets.QTreeWidgetItem()
            item.setText(0, path)
            item.setText(1, obj_type)
            if shape is not None:
                item.setText(2, str(shape))
            if dtype is not None:
                item.setText(3, str(dtype))
            root.addChild(item)
        
        self.structure_tree.expandAll()
        self.structure_tree.resizeColumnToContents(0)
    
    def _filter_metadata(self, text):
        if not hasattr(self, '_all_metadata'):
            return
        if not text:
            self._populate_metadata_table(self._all_metadata)
        else:
            filtered = [item for item in self._all_metadata if text.lower() in item[0].lower()]
            self._populate_metadata_table(filtered)
    
    def clear(self):
        self.metadata_table.setRowCount(0)
        self.structure_tree.clear()
        self.status_label.setText("No metadata loaded")
        self.status_label.setStyleSheet("color: #999; padding: 5px;")


class MultiResolutionImage:
    """Manages multi-resolution Zarr pyramid with chunk-based loading (z5py compatible)"""
    
    def __init__(self, zarr_group):
        self.zarr_group = zarr_group
        self.levels = []
        self.scales = []
        self._discover_pyramid()
    
    def _discover_pyramid(self):
        """Discover pyramid levels in Zarr group - supports multiple formats"""
        # Try OME-NGFF format first
        try:
            attrs = dict(self.zarr_group.attrs) if hasattr(self.zarr_group, 'attrs') else {}
            
            if 'multiscales' in attrs:
                multiscales = attrs['multiscales']
                if isinstance(multiscales, list) and len(multiscales) > 0:
                    datasets = multiscales[0].get('datasets', [])
                    for ds in datasets:
                        path = ds.get('path', '')
                        if path in self.zarr_group:
                            self.levels.append(self.zarr_group[path])
                            # Get scale info
                            if 'coordinateTransformations' in ds:
                                transforms = ds['coordinateTransformations']
                                scale = None
                                for t in transforms:
                                    if t.get('type') == 'scale':
                                        scale_vals = t.get('scale', [1.0, 1.0, 1.0])
                                        # Get last 2 dims (y, x) or last 3 if 3D
                                        scale = scale_vals[-2:] if len(scale_vals) >= 2 else [1.0, 1.0]
                                        break
                                self.scales.append(scale or [1.0, 1.0])
                            else:
                                self.scales.append([1.0, 1.0])
        except Exception as e:
            print(f"Note: Could not parse multiscales metadata: {e}")
        
        # Fallback: look for numeric pyramid (0, 1, 2, ...)
        if not self.levels:
            level_idx = 0
            while str(level_idx) in self.zarr_group:
                try:
                    array = self.zarr_group[str(level_idx)]
                    # Check if it's an array-like object
                    if hasattr(array, 'shape') and hasattr(array, 'dtype'):
                        self.levels.append(array)
                        # Estimate scale from shape ratios
                        if level_idx == 0:
                            self.scales.append([1.0, 1.0])
                        else:
                            prev_shape = self.levels[0].shape
                            curr_shape = array.shape
                            # Handle different dimensionalities
                            scale_y = prev_shape[-2] / curr_shape[-2] if len(curr_shape) >= 2 else 1.0
                            scale_x = prev_shape[-1] / curr_shape[-1] if len(curr_shape) >= 1 else 1.0
                            self.scales.append([scale_y, scale_x])
                        level_idx += 1
                    else:
                        break
                except Exception as e:
                    print(f"Warning: Could not load level {level_idx}: {e}")
                    break
        
        # Last resort: look for any array-like objects
        if not self.levels:
            try:
                for key in self.zarr_group.keys():
                    try:
                        obj = self.zarr_group[key]
                        if hasattr(obj, 'shape') and hasattr(obj, 'dtype'):
                            self.levels.append(obj)
                            self.scales.append([1.0, 1.0])
                    except:
                        pass
            except:
                pass
        
        if not self.levels:
            raise ValueError("No pyramid levels found in Zarr group. Cannot find any datasets.")
        
        print(f"Found {len(self.levels)} pyramid levels")
        for i, level in enumerate(self.levels):
            print(f"  Level {i}: shape={level.shape}, scale={self.scales[i]}")
    
    def get_num_levels(self):
        """Get number of pyramid levels"""
        return len(self.levels)
    
    def get_level_shape(self, level):
        """Get shape of specific pyramid level"""
        if 0 <= level < len(self.levels):
            return self.levels[level].shape
        return None
    
    def get_optimal_level(self, view_scale):
        """
        Determine optimal pyramid level based on view scale
        view_scale: pixels per data point (zoom level)
        """
        if view_scale >= 1.0:
            return 0  # Use highest resolution
        
        # Find level where pixel:data ratio is closest to 1:1
        for i, scale in enumerate(self.scales):
            avg_scale = (scale[0] + scale[1]) / 2
            if view_scale * avg_scale >= 0.5:
                return i
        
        return len(self.levels) - 1  # Use lowest resolution
    
    def get_chunk_data(self, level, slice_idx, y_range, x_range):
        """
        Load data chunk at specific level and ranges
        
        Parameters:
        -----------
        level : int
            Pyramid level
        slice_idx : int
            Slice/timepoint index (for 3D data)
        y_range : tuple
            (y_start, y_end)
        x_range : tuple
            (x_start, x_end)
        
        Returns:
        --------
        numpy array of requested region
        """
        if level < 0 or level >= len(self.levels):
            return None
        
        array = self.levels[level]
        shape = array.shape
        
        # Handle different dimensionalities
        ndim = len(shape)
        
        # Clamp ranges to valid bounds
        y_start, y_end = y_range
        x_start, x_end = x_range
        
        y_start = max(0, min(y_start, shape[-2]))
        y_end = max(0, min(y_end, shape[-2]))
        x_start = max(0, min(x_start, shape[-1]))
        x_end = max(0, min(x_end, shape[-1]))
        
        if y_start >= y_end or x_start >= x_end:
            return np.zeros((y_end - y_start, x_end - x_start), dtype=array.dtype)
        
        try:
            # Load data based on dimensionality
            if ndim == 2:
                # 2D image
                return np.array(array[y_start:y_end, x_start:x_end])
            elif ndim == 3:
                # 3D stack (z, y, x) or (t, y, x)
                slice_idx = min(slice_idx, shape[0] - 1)
                return np.array(array[slice_idx, y_start:y_end, x_start:x_end])
            elif ndim == 4:
                # 4D data (t, z, y, x) or (t, c, y, x)
                slice_idx = min(slice_idx, shape[0] - 1)
                return np.array(array[slice_idx, 0, y_start:y_end, x_start:x_end])
            elif ndim == 5:
                # 5D data (t, c, z, y, x)
                slice_idx = min(slice_idx, shape[0] - 1)
                return np.array(array[slice_idx, 0, 0, y_start:y_end, x_start:x_end])
        except Exception as e:
            print(f"Error loading chunk: {e}")
            return np.zeros((y_end - y_start, x_end - x_start), dtype=array.dtype)
        
        return None


class DynamicImageView(pg.ImageView):
    """Extended ImageView with dynamic chunk loading"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.multires_image = None
        self.current_level = 0
        self.current_slice = 0
        self.view_changed_timer = QtCore.QTimer()
        self.view_changed_timer.setSingleShot(True)
        self.view_changed_timer.timeout.connect(self._reload_visible_region)
        
        # Connect to view range changes
        self.view.sigRangeChanged.connect(self._on_view_changed)
    
    def set_multires_image(self, multires_image):
        """Set the multi-resolution image source"""
        self.multires_image = multires_image
        self.current_level = 0
        self.current_slice = 0
        self._reload_visible_region()
    
    def set_slice(self, slice_idx):
        """Set current slice/timepoint"""
        self.current_slice = slice_idx
        self._reload_visible_region()
    
    def _on_view_changed(self):
        """Handle view range change (zoom/pan)"""
        # Debounce: wait 100ms before reloading
        self.view_changed_timer.start(100)
    
    def _reload_visible_region(self):
        """Reload visible region at appropriate resolution"""
        if self.multires_image is None:
            return
        
        try:
            # Get view rectangle in data coordinates
            view_rect = self.view.viewRect()
            
            # Get current view scale (pixels per data point)
            view_box = self.view.viewRect()
            widget_size = self.view.size()
            
            if widget_size.width() > 0 and view_box.width() > 0:
                pixels_per_data_x = widget_size.width() / view_box.width()
                pixels_per_data_y = widget_size.height() / view_box.height()
                view_scale = min(pixels_per_data_x, pixels_per_data_y)
            else:
                view_scale = 1.0
            
            # Determine optimal level
            optimal_level = self.multires_image.get_optimal_level(view_scale)
            self.current_level = optimal_level
            
            # Get level shape
            level_shape = self.multires_image.get_level_shape(optimal_level)
            if level_shape is None:
                return
            
            height, width = level_shape[-2:]
            
            # Calculate visible region with padding
            padding_factor = 0.2  # Load 20% extra around edges
            x_padding = view_rect.width() * padding_factor
            y_padding = view_rect.height() * padding_factor
            
            x_start = int(max(0, view_rect.left() - x_padding))
            x_end = int(min(width, view_rect.right() + x_padding))
            y_start = int(max(0, view_rect.top() - y_padding))
            y_end = int(min(height, view_rect.bottom() + y_padding))
            
            # Load chunk
            chunk_data = self.multires_image.get_chunk_data(
                optimal_level, 
                self.current_slice,
                (y_start, y_end),
                (x_start, x_end)
            )
            
            if chunk_data is not None and chunk_data.size > 0:
                # Create full image with chunk placed correctly
                full_image = np.zeros((height, width), dtype=chunk_data.dtype)
                full_image[y_start:y_end, x_start:x_end] = chunk_data
                
                # Update display without auto-ranging (preserve zoom)
                self.setImage(full_image, autoLevels=False, autoRange=False)
                
                # Emit signal with current level info
                self.parent().update_level_info(optimal_level, level_shape)
                
        except Exception as e:
            print(f"Error loading region: {e}")


class ZarrMultiResViewer(QtWidgets.QDialog):
    """Main viewer for multi-resolution Zarr files"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.zarr_store = None
        self.zarr_group = None
        self.multires_image = None
        
        self.setWindowTitle("Multi-Resolution Zarr Viewer")
        self.setModal(False)
        self.resize(1600, 900)
        
        self._build_ui()
    
    def _build_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        
        # Main tabs
        self.main_tabs = QtWidgets.QTabWidget()
        
        # Image viewer tab
        image_tab = QtWidgets.QWidget()
        self._build_image_tab(image_tab)
        self.main_tabs.addTab(image_tab, "Image Viewer")
        
        # Metadata viewer tab
        self.metadata_viewer = MetadataViewer()
        self.main_tabs.addTab(self.metadata_viewer, "Metadata")
        
        main_layout.addWidget(self.main_tabs)
    
    def _build_image_tab(self, parent):
        layout = QtWidgets.QHBoxLayout(parent)
        
        # Left control panel
        left_panel = QtWidgets.QWidget()
        left_panel.setMaximumWidth(350)
        control_layout = QtWidgets.QVBoxLayout(left_panel)
        
        # Title
        title = QtWidgets.QLabel("Multi-Resolution Zarr Viewer")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        control_layout.addWidget(title)
        
        # File selection
        file_group = QtWidgets.QGroupBox("File Selection")
        file_layout = QtWidgets.QVBoxLayout()
        
        self.file_path_label = QtWidgets.QLabel("No file loaded")
        self.file_path_label.setWordWrap(True)
        self.file_path_label.setStyleSheet("color: #999;")
        file_layout.addWidget(self.file_path_label)
        
        load_btn = QtWidgets.QPushButton("Load Zarr Store")
        load_btn.clicked.connect(self._load_file)
        file_layout.addWidget(load_btn)
        
        file_group.setLayout(file_layout)
        control_layout.addWidget(file_group)
        
        # Pyramid info
        pyramid_group = QtWidgets.QGroupBox("Pyramid Information")
        pyramid_layout = QtWidgets.QFormLayout()
        
        self.num_levels_label = QtWidgets.QLabel("N/A")
        self.current_level_label = QtWidgets.QLabel("N/A")
        self.level_shape_label = QtWidgets.QLabel("N/A")
        self.level_chunks_label = QtWidgets.QLabel("N/A")
        
        pyramid_layout.addRow("Total levels:", self.num_levels_label)
        pyramid_layout.addRow("Current level:", self.current_level_label)
        pyramid_layout.addRow("Level shape:", self.level_shape_label)
        pyramid_layout.addRow("Chunk size:", self.level_chunks_label)
        
        pyramid_group.setLayout(pyramid_layout)
        control_layout.addWidget(pyramid_group)
        
        # Slice selection (for 3D/4D/5D data)
        slice_group = QtWidgets.QGroupBox("Slice/Time Selection")
        slice_layout = QtWidgets.QVBoxLayout()
        
        slider_layout = QtWidgets.QHBoxLayout()
        slider_layout.addWidget(QtWidgets.QLabel("Index:"))
        
        self.slice_label = QtWidgets.QLabel("0")
        self.slice_label.setMinimumWidth(50)
        self.slice_label.setStyleSheet("font-weight: bold;")
        slider_layout.addWidget(self.slice_label)
        slice_layout.addLayout(slider_layout)
        
        self.slice_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slice_slider.setMinimum(0)
        self.slice_slider.setMaximum(0)
        self.slice_slider.setEnabled(False)
        self.slice_slider.valueChanged.connect(self._on_slice_changed)
        slice_layout.addWidget(self.slice_slider)
        
        slice_group.setLayout(slice_layout)
        control_layout.addWidget(slice_group)
        
        # Contrast control
        contrast_group = QtWidgets.QGroupBox("Contrast Control")
        contrast_layout = QtWidgets.QVBoxLayout()
        
        self.auto_level_combo = QtWidgets.QComboBox()
        self.auto_level_combo.addItems([
            "Auto (default)",
            "Min/Max",
            "Percentile 1-99%",
            "Percentile 2-98%",
            "Manual"
        ])
        self.auto_level_combo.currentIndexChanged.connect(self._on_contrast_changed)
        contrast_layout.addWidget(self.auto_level_combo)
        
        # Manual controls
        manual_widget = QtWidgets.QWidget()
        manual_layout = QtWidgets.QFormLayout()
        manual_layout.setContentsMargins(0, 0, 0, 0)
        
        self.min_spin = QtWidgets.QDoubleSpinBox()
        self.min_spin.setRange(-1e10, 1e10)
        self.min_spin.setDecimals(4)
        manual_layout.addRow("Min:", self.min_spin)
        
        self.max_spin = QtWidgets.QDoubleSpinBox()
        self.max_spin.setRange(-1e10, 1e10)
        self.max_spin.setDecimals(4)
        manual_layout.addRow("Max:", self.max_spin)
        
        manual_widget.setLayout(manual_layout)
        manual_widget.setVisible(False)
        self.manual_controls = manual_widget
        contrast_layout.addWidget(manual_widget)
        
        contrast_group.setLayout(contrast_layout)
        control_layout.addWidget(contrast_group)
        
        # View controls
        view_group = QtWidgets.QGroupBox("View Controls")
        view_layout = QtWidgets.QVBoxLayout()
        
        reset_view_btn = QtWidgets.QPushButton("Reset View")
        reset_view_btn.clicked.connect(self._reset_view)
        view_layout.addWidget(reset_view_btn)
        
        self.view_info_label = QtWidgets.QLabel(
            "<b>Navigation:</b><br>"
            "• Mouse wheel: Zoom<br>"
            "• Right drag: Pan<br>"
            "• Left click: Select<br>"
            "<br>"
            "Resolution automatically adjusts to zoom level"
        )
        self.view_info_label.setWordWrap(True)
        self.view_info_label.setStyleSheet("padding: 10px; background-color: #2a2a2a; border-radius: 5px;")
        view_layout.addWidget(self.view_info_label)
        
        view_group.setLayout(view_layout)
        control_layout.addWidget(view_group)
        
        # Statistics
        stats_group = QtWidgets.QGroupBox("Image Statistics")
        stats_layout = QtWidgets.QFormLayout()
        
        self.min_val_label = QtWidgets.QLabel("N/A")
        self.max_val_label = QtWidgets.QLabel("N/A")
        self.mean_val_label = QtWidgets.QLabel("N/A")
        
        stats_layout.addRow("Min:", self.min_val_label)
        stats_layout.addRow("Max:", self.max_val_label)
        stats_layout.addRow("Mean:", self.mean_val_label)
        
        stats_group.setLayout(stats_layout)
        control_layout.addWidget(stats_group)
        
        control_layout.addStretch()
        layout.addWidget(left_panel)
        
        # Right panel - Image display
        right_panel = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        self.image_view = DynamicImageView()
        self.image_view.ui.roiBtn.hide()
        self.image_view.ui.menuBtn.hide()
        right_layout.addWidget(self.image_view)
        
        layout.addWidget(right_panel)
        layout.setStretch(1, 1)
    
    def _load_file(self):
        """Load Zarr store (directory or zip) using z5py"""
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select Zarr Store Directory"
        )
        
        if not path:
            # Try opening as zip file
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "Open Zarr Store (zip)", "", "Zip Files (*.zip);;All Files (*)"
            )
        
        if not path:
            return
        
        try:
            # Close previous store
            if self.zarr_store is not None:
                try:
                    self.zarr_store.close()
                except:
                    pass
            
            # Open Zarr store using z5py
            if path.endswith('.zip'):
                # z5py can open zip files directly
                self.zarr_store = z5py.File(path, mode='r', use_zarr_format=True)
            else:
                # Open directory as Zarr
                self.zarr_store = z5py.File(path, mode='r', use_zarr_format=True)
            
            self.zarr_group = self.zarr_store
            
            # Create multi-resolution image handler
            self.multires_image = MultiResolutionImage(self.zarr_group)
            
            # Update UI
            self.file_path_label.setText(Path(path).name)
            self.file_path_label.setStyleSheet("color: white;")
            
            # Update pyramid info
            num_levels = self.multires_image.get_num_levels()
            self.num_levels_label.setText(str(num_levels))
            
            # Get first level info
            level_0_shape = self.multires_image.get_level_shape(0)
            self.level_shape_label.setText(str(level_0_shape))
            
            # Check if 3D+ data
            if len(level_0_shape) > 2:
                num_slices = level_0_shape[0]
                self.slice_slider.setMaximum(num_slices - 1)
                self.slice_slider.setEnabled(True)
            else:
                self.slice_slider.setEnabled(False)
            
            # Set up image view
            self.image_view.set_multires_image(self.multires_image)
            
            # Load metadata
            self.metadata_viewer.load_metadata(self.zarr_group)
            
            # Update chunks info
            level_0 = self.multires_image.levels[0]
            if hasattr(level_0, 'chunks'):
                self.level_chunks_label.setText(str(level_0.chunks))
            else:
                self.level_chunks_label.setText("N/A")
            
            QtWidgets.QMessageBox.information(
                self, "Success", 
                f"Loaded {num_levels} pyramid levels\n"
                f"Highest resolution: {level_0_shape}"
            )
            
        except Exception as e:
            import traceback
            error_msg = f"Failed to load Zarr store:\n{str(e)}\n\n{traceback.format_exc()}"
            print(error_msg)
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Failed to load Zarr store:\n{str(e)}"
            )
    
    def _on_slice_changed(self, value):
        """Handle slice slider change"""
        self.slice_label.setText(str(value))
        if self.image_view.multires_image is not None:
            self.image_view.set_slice(value)
    
    def _on_contrast_changed(self, index):
        """Handle contrast mode change"""
        is_manual = (index == 4)
        self.manual_controls.setVisible(is_manual)
    
    def _reset_view(self):
        """Reset view to show entire image"""
        self.image_view.view.autoRange()
    
    def update_level_info(self, level, shape):
        """Update current level information (called by DynamicImageView)"""
        self.current_level_label.setText(f"{level}")
        self.level_shape_label.setText(str(shape))
        
        # Update chunks info
        if self.multires_image and level < len(self.multires_image.levels):
            current_array = self.multires_image.levels[level]
            if hasattr(current_array, 'chunks'):
                self.level_chunks_label.setText(str(current_array.chunks))
    
    def closeEvent(self, event):
        """Clean up on close"""
        if self.zarr_store is not None:
            try:
                self.zarr_store.close()
            except:
                pass
        super().closeEvent(event)


def apply_dark_theme(app):
    """Apply dark theme to application"""
    app.setStyle('Fusion')
    palette = QtGui.QPalette()
    
    palette.setColor(QtGui.QPalette.Window, QtGui.QColor(53, 53, 53))
    palette.setColor(QtGui.QPalette.WindowText, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.Base, QtGui.QColor(35, 35, 35))
    palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(53, 53, 53))
    palette.setColor(QtGui.QPalette.Text, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.Button, QtGui.QColor(53, 53, 53))
    palette.setColor(QtGui.QPalette.ButtonText, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor(42, 130, 218))
    palette.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.white)
    
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
            padding: 0 5px;
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
        }
        QPushButton:pressed {
            background-color: #3a3a3a;
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
        QTableWidget {
            gridline-color: #555;
        }
        QHeaderView::section {
            background-color: #454545;
            padding: 5px;
            border: 1px solid #555;
        }
        QTabWidget::pane {
            border: 1px solid #555;
        }
        QTabBar::tab {
            background-color: #454545;
            border: 1px solid #555;
            padding: 8px 16px;
        }
        QTabBar::tab:selected {
            background-color: #2a82da;
        }
    """)


def main():
    """Run the Zarr multi-resolution viewer"""
    import sys
    
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    
    app.setApplicationName("Zarr Multi-Resolution Viewer")
    apply_dark_theme(app)
    
    viewer = ZarrMultiResViewer()
    viewer.show()
    
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
