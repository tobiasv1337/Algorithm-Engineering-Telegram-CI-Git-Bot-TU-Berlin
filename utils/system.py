class ShutdownSignal:
    flag = False


def handle_shutdown_signal(signum, frame):
    """Signal handler to set the shutdown flag."""
    global shutdown_flag
    print(f"\nSignal {signum} received. Shutting down gracefully...")
    ShutdownSignal.flag = True
