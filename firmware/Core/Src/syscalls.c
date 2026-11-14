/* No POSIX streams are used by the firmware; CLI uses a fixed USB queue. */
#include <errno.h>
#include <sys/stat.h>
#include <stddef.h>
int _close(int fd) { (void)fd; errno=EBADF; return -1; }
int _lseek(int fd,int offset,int whence) { (void)fd; (void)offset; (void)whence; errno=ESPIPE; return -1; }
int _read(int fd,char *p,int n) { (void)fd; (void)p; (void)n; errno=EBADF; return -1; }
int _write(int fd,const char *p,int n) { (void)fd; (void)p; (void)n; errno=EBADF; return -1; }
int _fstat(int fd,struct stat *s) { (void)fd; s->st_mode=S_IFCHR; return 0; }
int _isatty(int fd) { (void)fd; return 1; }
void *_sbrk(ptrdiff_t increment) { (void)increment; errno=ENOMEM; return (void*)-1; }
