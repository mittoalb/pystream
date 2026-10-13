# Build the architecture slide decks.
#
# Dependencies (all fetched via npx on first run):
#   @marp-team/marp-cli       — turns markdown into HTML/PDF/PPTX
#   @mermaid-js/mermaid-cli   — renders ```mermaid blocks to SVG at
#                                build time so Marp sees plain images
#                                (no browser JS, no CDN dependency,
#                                 no cache weirdness)
#
# Build pipeline:
#   src/<deck>.md
#     -> _build/.processed/<deck>.md   (mmdc-rendered: mermaid → img/*.svg)
#     -> _build/<deck>.html|pdf|pptx   (marp-cli)
#
# Targets:
#   make html    one .html per deck
#   make pdf     one .pdf per deck (requires Chromium / Chrome installed)
#   make pptx    one .pptx per deck
#   make serve   live-reload browser preview
#   make clean   remove _build/

MARP     ?= npx --yes @marp-team/marp-cli
RENDER   := python3 _render_mermaid.py
BUILD    ?= _build

SRC      := $(sort $(wildcard [0-9][0-9]-*.md))
HTML     := $(patsubst %.md,$(BUILD)/%.html,$(SRC))
PDF      := $(patsubst %.md,$(BUILD)/%.pdf,$(SRC))
PPTX     := $(patsubst %.md,$(BUILD)/%.pptx,$(SRC))

PROCESSED_DIR := $(BUILD)/.processed
# SVGs land next to the final HTML (in $(BUILD)/img/) so the generated
# `<img src="img/...">` resolves relative to the HTML page, not relative
# to the intermediate .processed/ markdown.
IMG_DIR       := $(BUILD)/img

MARP_FLAGS := --html --allow-local-files --theme-set beamline.css

.PHONY: all html pdf pptx serve clean

all: html

html: $(HTML)
pdf:  $(PDF)
pptx: $(PPTX)

# Pre-render mermaid blocks to SVG, rewrite source markdown to
# reference them as images. mmdc caches by SHA so re-runs that haven't
# changed a diagram are instant after the first build.
$(PROCESSED_DIR)/%.md: %.md _render_mermaid.py | $(PROCESSED_DIR)
	$(RENDER) $< $@ $(IMG_DIR)

# Mirror hand-authored screenshots into _build/img/ so `img/screenshots/*.png`
# paths in the markdown resolve from the final HTML location.
screenshots: | $(BUILD)
	@mkdir -p $(BUILD)/img
	@if [ -d img/screenshots ]; then \
		cp -r img/screenshots $(BUILD)/img/; \
	fi

html pdf pptx: screenshots

.PHONY: screenshots

$(BUILD)/%.html: $(PROCESSED_DIR)/%.md | $(BUILD)
	$(MARP) $(MARP_FLAGS) -o $@ $<

$(BUILD)/%.pdf: $(PROCESSED_DIR)/%.md | $(BUILD)
	$(MARP) $(MARP_FLAGS) --pdf -o $@ $<

$(BUILD)/%.pptx: $(PROCESSED_DIR)/%.md | $(BUILD)
	$(MARP) $(MARP_FLAGS) --pptx -o $@ $<

$(BUILD) $(PROCESSED_DIR):
	mkdir -p $@

serve:
	$(MARP) $(MARP_FLAGS) --server .

clean:
	rm -rf $(BUILD)
