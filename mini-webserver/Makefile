CC = cc
CPPFLAGS = -D_POSIX_C_SOURCE=200809L -D_DEFAULT_SOURCE -Iinclude
CFLAGS = -std=c11 -O2 -g -Wall -Wextra -Wpedantic -Werror
LDFLAGS =
LDLIBS = -pthread
BUILD = build
MODULES = src/net.c src/http.c src/config.c src/static.c src/proxy.c src/app.c src/pool.c

.PHONY: all test unit integration smoke sanitize sanitize-test valgrind benchmark clean
all: $(BUILD)/mini-webserver

$(BUILD):
	mkdir -p $(BUILD)

$(BUILD)/mini-webserver: src/main.c $(MODULES) include/web.h | $(BUILD)
	$(CC) $(CPPFLAGS) $(CFLAGS) src/main.c $(MODULES) $(LDFLAGS) $(LDLIBS) -o $@

$(BUILD)/test-unit: tests/test_unit.c $(MODULES) include/web.h | $(BUILD)
	$(CC) $(CPPFLAGS) $(CFLAGS) tests/test_unit.c $(MODULES) $(LDFLAGS) $(LDLIBS) -o $@

unit: $(BUILD)/test-unit
	$(BUILD)/test-unit

integration: all
	python3 tests/test_integration.py --binary $(BUILD)/mini-webserver

test: unit integration

smoke: all
	python3 tests/smoke.py --binary $(BUILD)/mini-webserver

sanitize:
	$(MAKE) BUILD=build-sanitize CFLAGS='-std=c11 -O1 -g -Wall -Wextra -Wpedantic -Werror -fno-omit-frame-pointer -fsanitize=address,undefined' LDFLAGS='-fsanitize=address,undefined' all unit

sanitize-test: sanitize
	ASAN_OPTIONS=detect_leaks=1:abort_on_error=1 python3 tests/test_integration.py --binary build-sanitize/mini-webserver

valgrind: all
	python3 tests/check_valgrind.py --binary $(BUILD)/mini-webserver

benchmark: all
	python3 tests/benchmark.py --binary $(BUILD)/mini-webserver

clean:
	rm -f build/mini-webserver build/test-unit build-sanitize/mini-webserver build-sanitize/test-unit
