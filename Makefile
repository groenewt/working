.PHONY: all build render render-research-appendix install-research-appendix validate-research-render render-encyclopedia render-duckdb-projection build-duckdb-projection audit clean-research-render

RUBY ?= ruby
RESEARCH_RENDER_SCRIPT := research/specs/data/research/render/render_research_appendix.rb
empty :=
space := $(empty) $(empty)
NVM_NODE_BINS := $(wildcard $(HOME)/.nvm/versions/node/*/bin)
RESEARCH_RENDER_PATH := $(PATH)$(if $(NVM_BIN),:$(NVM_BIN))$(if $(NVM_NODE_BINS),:$(subst $(space),:,$(NVM_NODE_BINS))):$(HOME)/node_modules/.bin
RESEARCH_RENDER_ENV := PATH="$(RESEARCH_RENDER_PATH)"

all: build

build: render-encyclopedia

render: build

render-research-appendix:
	$(RESEARCH_RENDER_ENV) $(RUBY) $(RESEARCH_RENDER_SCRIPT) --repo-root "$(CURDIR)" --mode generate

install-research-appendix: render-research-appendix
	$(RESEARCH_RENDER_ENV) $(RUBY) $(RESEARCH_RENDER_SCRIPT) --repo-root "$(CURDIR)" --mode install

validate-research-render: install-research-appendix
	$(RESEARCH_RENDER_ENV) $(RUBY) $(RESEARCH_RENDER_SCRIPT) --repo-root "$(CURDIR)" --mode validate

render-encyclopedia: validate-research-render
	$(MAKE) -C working build

render-duckdb-projection: validate-research-render
	$(MAKE) -C working build-duckdb-projection

build-duckdb-projection: render-duckdb-projection

audit: validate-research-render
	$(MAKE) -C working audit

clean-research-render:
	rm -rf research/build/specs/research research/specs/data/research/render/out
