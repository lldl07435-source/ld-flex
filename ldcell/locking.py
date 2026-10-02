from pathlib import Path
import os

class DataLock:
    def __init__(self, root):
        Path(root).mkdir(parents=True,exist_ok=True)
        self.file=(Path(root)/'.session.lock').open('a+b')
        if self.file.tell()==0:self.file.write(b'0');self.file.flush()
        self.file.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close();raise RuntimeError('此数据目录已被另一个工作台或实验进程使用，请关闭旧窗口')

    def close(self):
        if self.file.closed:return
        self.file.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(self.file.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            fcntl.flock(self.file,fcntl.LOCK_UN)
        self.file.close()

    def __enter__(self):return self
    def __exit__(self,*args):self.close()
