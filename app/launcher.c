// OneDock.app launcher: runs scripts/start.sh as a child process so macOS
// attributes permissions to OneDock. Log: ~/Library/Logs/Dock/dock.log
#include <libgen.h>
#include <mach-o/dyld.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <fcntl.h>
#include <unistd.h>

extern char **environ;
static pid_t child = 0;

static void pass_on(int sig) {
    if (child > 0) kill(-child, sig);  // Dock and everything it started
}

int main(void) {
    char exe[4096], root[4096], file[4200], script[4200], logs[4200], log[4300];
    uint32_t size = sizeof exe;
    if (_NSGetExecutablePath(exe, &size) != 0) return 1;

    // Contents/Resources/root holds the Dock folder path (written by build_app.sh).
    snprintf(file, sizeof file, "%s/../Resources/root", dirname(exe));
    FILE *f = fopen(file, "r");
    if (!f || !fgets(root, sizeof root, f)) return 1;
    fclose(f);
    root[strcspn(root, "\n")] = 0;
    snprintf(script, sizeof script, "%s/scripts/start.sh", root);

    const char *home = getenv("HOME");
    snprintf(logs, sizeof logs, "%s/Library/Logs/Dock", home ? home : "/tmp");
    mkdir(logs, 0755);
    snprintf(log, sizeof log, "%s/dock.log", logs);

    posix_spawn_file_actions_t files;
    posix_spawn_file_actions_init(&files);
    posix_spawn_file_actions_addopen(&files, 1, log, O_WRONLY | O_CREAT | O_APPEND, 0644);
    posix_spawn_file_actions_adddup2(&files, 1, 2);

    posix_spawnattr_t attr;
    posix_spawnattr_init(&attr);
    posix_spawnattr_setflags(&attr, POSIX_SPAWN_SETPGROUP);  // its own group, so Quit can stop all of it
    posix_spawnattr_setpgroup(&attr, 0);

    signal(SIGTERM, pass_on);
    signal(SIGINT, pass_on);
    char *args[] = {"/bin/bash", script, NULL};
    if (posix_spawn(&child, "/bin/bash", &files, &attr, args, environ) != 0) return 1;

    int status;
    while (waitpid(child, &status, 0) < 0) {}  // (interrupted by a signal: keep waiting)
    return 0;
}
