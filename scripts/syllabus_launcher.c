#include <limits.h>
#include <libgen.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(void) {
    char executable_path[PATH_MAX];
    uint32_t executable_size = sizeof(executable_path);
    if (_NSGetExecutablePath(executable_path, &executable_size) != 0) {
        return 1;
    }

    char resolved_executable[PATH_MAX];
    if (!realpath(executable_path, resolved_executable)) {
        strncpy(resolved_executable, executable_path, sizeof(resolved_executable) - 1);
        resolved_executable[sizeof(resolved_executable) - 1] = '\0';
    }

    char directory_buffer[PATH_MAX];
    strncpy(directory_buffer, resolved_executable, sizeof(directory_buffer) - 1);
    directory_buffer[sizeof(directory_buffer) - 1] = '\0';
    char *macos_directory = dirname(directory_buffer);

    char resource_root[PATH_MAX];
    snprintf(resource_root, sizeof(resource_root), "%s/../Resources", macos_directory);
    char resolved_resource_root[PATH_MAX];
    if (!realpath(resource_root, resolved_resource_root)) {
        return 1;
    }

    char application_path[PATH_MAX];
    snprintf(application_path, sizeof(application_path), "%s/syllabus_search_app.py", resolved_resource_root);
    if (chdir(resolved_resource_root) != 0) {
        return 1;
    }

    const char *python = "/Library/Frameworks/Python.framework/Versions/3.14/bin/python3";
    execl("/usr/bin/arch", "arch", "-arm64", python, application_path, (char *)NULL);
    return 1;
}
