#include <errno.h>
#include <libgen.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static int file_exists(const char *path) {
    struct stat st;
    return stat(path, &st) == 0 && S_ISREG(st.st_mode);
}

static void append_log(const char *log_path, const char *message) {
    FILE *log = fopen(log_path, "a");
    if (!log) {
        return;
    }
    fputs(message, log);
    fputc('\n', log);
    fclose(log);
}

int main(void) {
    char exe_path[PATH_MAX];
    uint32_t exe_size = sizeof(exe_path);
    if (_NSGetExecutablePath(exe_path, &exe_size) != 0) {
        return 1;
    }

    char real_exe[PATH_MAX];
    if (!realpath(exe_path, real_exe)) {
        strncpy(real_exe, exe_path, sizeof(real_exe) - 1);
        real_exe[sizeof(real_exe) - 1] = '\0';
    }

    char path_buffer[PATH_MAX];
    strncpy(path_buffer, real_exe, sizeof(path_buffer) - 1);
    path_buffer[sizeof(path_buffer) - 1] = '\0';
    char *macos_dir = dirname(path_buffer);

    char app_root[PATH_MAX];
    snprintf(app_root, sizeof(app_root), "%s/../../..", macos_dir);
    char resolved_app_root[PATH_MAX];
    if (!realpath(app_root, resolved_app_root)) {
        snprintf(resolved_app_root, sizeof(resolved_app_root), "/Users/akamatsunaoaki/Documents/kakomon");
    }

    char resource_root[PATH_MAX];
    snprintf(resource_root, sizeof(resource_root), "%s/過去問検索.app/Contents/Resources", resolved_app_root);
    char desktop_app[PATH_MAX];
    snprintf(desktop_app, sizeof(desktop_app), "%s/desktop_app.py", resource_root);
    if (!file_exists(desktop_app)) {
        snprintf(resolved_app_root, sizeof(resolved_app_root), "/Users/akamatsunaoaki/Documents/kakomon");
        snprintf(resource_root, sizeof(resource_root), "%s/過去問検索.app/Contents/Resources", resolved_app_root);
        snprintf(desktop_app, sizeof(desktop_app), "%s/desktop_app.py", resource_root);
    }

    char log_path[PATH_MAX];
    snprintf(log_path, sizeof(log_path), "%s/kakomon_app.log", resolved_app_root);
    append_log(log_path, "==== native launcher ====");
    append_log(log_path, desktop_app);

    char kakomon_root[PATH_MAX];
    const char *home = getenv("HOME");
    if (!home) {
        home = "/Users/akamatsunaoaki";
    }
    snprintf(kakomon_root, sizeof(kakomon_root), "%s/Library/Application Support/Kakomon", home);
    setenv("KAKOMON_ROOT", kakomon_root, 1);
    setenv("KAKOMON_SEED_ROOT", resource_root, 1);

    if (chdir(resource_root) != 0) {
        char error_message[PATH_MAX + 80];
        snprintf(error_message, sizeof(error_message), "ERROR: chdir failed: %s: %s", resource_root, strerror(errno));
        append_log(log_path, error_message);
        return 1;
    }

    const char *python = "/Library/Frameworks/Python.framework/Versions/3.14/bin/python3";
    execl("/usr/bin/arch", "arch", "-arm64", python, desktop_app, (char *)NULL);

    char error_message[PATH_MAX + 80];
    snprintf(error_message, sizeof(error_message), "ERROR: exec failed: %s", strerror(errno));
    append_log(log_path, error_message);
    return 1;
}
