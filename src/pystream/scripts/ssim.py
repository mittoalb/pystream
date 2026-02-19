lbl_stats = QtWidgets.QLabel("Waiting for frames...")
        btn_layout.addWidget(self.lbl_stats)

        layout.addLayout(btn_layout)

        # Image view
        self.image_view = pg.ImageView()
        self.image_view.ui.roiBtn.hide()
        self.image_view.ui.menuBtn.hide()
        layout.addWidget(self.image_view)

        self._update_buttons()

    def _on_start(self):
        self.running = True
        self.paused = False
        self._update_buttons()

    def _on_pause(self):
        if self.running:
            self.paused = not self.paused
            self._update_buttons()

    def _update_buttons(self):
        if self.running and not self.paused:
            self.btn_start.setText("Running")
            self.btn_start.setEnabled(False)
            self.btn_pause.setText("Pause")
            self.btn_pause.setEnabled(True)
        elif self.paused:
            self.btn_start.setText("Start")
            self.btn_start.setEnabled(True)
            self.btn_pause.setText("Paused")
            self.btn_pause.setEnabled(True)
        else:
            self.btn_start.setText("Start")
            self.btn_start.setEnabled(True)
            self.btn_pause.setText("Pause")
            self.btn_pause.setEnabled(False)

    def update_image(self, img, stats_text):
        if not self.running or self.paused:
            r
