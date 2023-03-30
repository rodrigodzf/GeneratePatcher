import queue
import re
import socket
import subprocess
import threading
import time
from typing import Optional

import gradio as gr
import hydra
import openai
from omegaconf import DictConfig


class Client:
    def __init__(
        self,
        host: str,  # host address
        port: int,  # port number
        sync: bool = False,  # sync mode
    ):
        self.host = host
        self.port = port
        self.sync = sync
        self.send_queue: queue.Queue[bytes] = queue.Queue()
        self.recv_queue: queue.Queue[bytes] = queue.Queue()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(None)  # blocking
        self.exit_signal = threading.Event()

        if not sync:
            self.send_thread = threading.Thread(target=self.__send)
            self.recv_thread = threading.Thread(target=self.__receive)

        self.connected = False

    def start(self):
        try:
            self.sock.connect((self.host, self.port))
            print("Client started")
            self.connected = True

            if not self.sync:
                self.send_thread.start()
                self.recv_thread.start()
        except socket.error as e:
            print("Socket error: %s" % str(e))

    def __receive(self):
        while not self.exit_signal.is_set():
            try:
                data = self.sock.recv(1024)
                if data:
                    self.recv_queue.put(data)
            except socket.timeout:
                pass

    def __send(self):
        while not self.exit_signal.is_set():
            try:
                data = self.send_queue.get_nowait()
                if data:
                    self.sock.send(data)
            except queue.Empty:
                pass

    def send(self, data) -> None:
        if not self.sync:
            self.send_queue.put(data)
        else:
            if self.sock.send(data) == 0:
                raise RuntimeError("Socket connection broken")

    def receive(self) -> Optional[str]:
        if not self.sync:
            try:
                data = self.recv_queue.get_nowait()
                return data.decode("utf-8")
            except queue.Empty:
                return None
        else:
            try:
                data = self.sock.recv(8192)
                return data.decode("utf-8")
            except:
                return None

    def close(self):
        self.exit_signal.set()
        self.sock.close()
        print("Client closed")


class TextUI:
    def __init__(
        self,
        model: str = "gpt-3.5-turbo",
        max_tokens: int = 2000,
        temperature: float = 0.0,
        top_p: float = 1,
        EOF: str = "###",
        pd_path: str = "/Applications/Pd-0.53-2.app/Contents/Resources/bin",
        **kwargs,
    ):
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.EOF = EOF
        

        self.system_prompt = f"""You are an assistant made for the purposes of helping the user with Pure Data. Do not respond with anything that is not Pure Data messages. Do not provide explanations. Do not provide examples. Do not create connections between objects that do not exist. Append '{EOF}' to the end of the patcher.

        Example:

        user: create an FM synth
        assistant:
        #N canvas 92 117 450 300 12;
        #X obj 218 172 *~;
        #X floatatom 218 87 5 0 0 0 - - - 0;
        #X floatatom 148 132 5 0 0 0 - - - 0;
        #X obj 148 202 +~;
        #X floatatom 236 142 4 0 0 0 - - - 0;
        #X text 123 89 carrier;
        #X text 122 107 frequency;
        #X text 203 63 frequency;
        #X text 204 46 modulation;
        #X obj 148 248 osc~;
        #X text 275 154 index;
        #X text 277 135 modulation;
        #X obj 218 112 osc~;
        #X obj 149 283 dac~;
        #X connect 0 0 3 1;
        #X connect 1 0 12 0;
        #X connect 2 0 3 0;
        #X connect 3 0 9 0;
        #X connect 4 0 0 1;
        #X connect 9 0 13 0;
        #X connect 12 0 0 0;
        {EOF}
        """

        # start pure data
        self.start_pd(pd_path=pd_path)
        # The port number is the same as the one used by the Pure Data patch
        # Don't forget to change it if you change the patch
        self.client = Client("localhost", 3001, sync=True)

        # create ui
        self.console_history = []
        self.prompt_history = [
            {
                "role": "system",
                "content": self.system_prompt,
            }
        ]
        self.create_ui()

        # connect to pure data
        self.client.start()

    def send_prompt(
        self,
        prompt: str = "Return a Pure Data patcher that generates a sine wave.",
    ):
        delimiter: str = f"Append an '{self.EOF}' to the end of the patcher."
        self.prompt_history.append(
            {
                "role": "user",
                "content": f"{prompt} {delimiter}",
            }
        )

        response = openai.ChatCompletion.create(
            model=self.model,
            messages=self.prompt_history,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            top_p=self.top_p,
            frequency_penalty=0,
            presence_penalty=0,
            stop=self.EOF,
            n=1,
        )
        ai_message = response["choices"][0]["message"]  # type: ignore
        content = str(ai_message["content"])  # type: ignore

        # Remove the first line
        content = content[content.find("\n") + 1:]
        # Remove the "#X " characters
        content = re.sub(r"#X ", "", content)

        # Clear the patcher
        self.clear_patcher()

        # Send to pure data server line by line
        ret = []
        for line in content.splitlines():
            self.client.send(line.encode("utf-8"))
            ret += [self.client.receive()]

        # Add to the response to the prompt history
        # Keep the first and the last 5 messages
        self.prompt_history.append(dict(ai_message))
        if len(self.prompt_history) > 6:
            self.prompt_history = self.prompt_history[0:1] + self.prompt_history[-5:]
        
        return content, ''.join(ret), self.prompt_history

    def clear_patcher(self):
        self.client.send("clear;".encode("utf-8"))
        self.client.receive()
        return None

    def start_pd(
        self,
        pd_path: str = "/Applications/Pd-0.53-2.app/Contents/Resources/bin",
        receive_patcher_path: str = "./receive.pd",
    ):
        # Start pure data
        cmd = (
            f"{pd_path}/pd -d 4 -open {receive_patcher_path} -stderr 2>&1 | while true; do {pd_path}/pdsend"
            " 9999 localhost udp; done"
        )
        subprocess.Popen(
            cmd,
            shell=True,
        )

        # Wait for pure data to start
        time.sleep(2)

        return "started pd"

    def get_pdconsole_output(self):
        # check the string is not empty and not null
        if self.client.connected:
            data = self.client.receive()
            if data is not None and data != "":
                self.console_history += [data]
            if self.console_history:
                return "".join(self.console_history)
        return

    def clear_console(self):
        # self.console_history.clear()
        return ""

    def create_ui(self):
        with gr.Blocks() as self.demo:
            with gr.Row():
                with gr.Column():
                    input = gr.Textbox(
                        value="Return a Pure Data patcher that generates a sine wave.",
                        placeholder=(
                            "Return a Pure Data patcher that generates a sine wave."
                        ),
                        lines=10,
                        label="Prompt",
                    )
                    
                    examples = gr.Examples(
                        [
                            "Create a noise generator",
                            "Create a low pass filter",
                            "Modulate the amplitude of the sine tone before the filter.",
                            "Create 5 tones that are added together.",
                        ],
                        label="Examples",
                        inputs=input,
                    )
                with gr.Column():
                    output = gr.Textbox(
                        placeholder="",
                        lines=10,
                        max_lines=10,
                        label="Pure Data patcher",
                    )
                    console = gr.Textbox(
                        # value=self.get_pdconsole_output,
                        value="",
                        placeholder="",
                        lines=10,
                        max_lines=10,
                        label="Pure Data console output",
                        # every=0.1,
                    )
            with gr.Row():
                history = gr.JSON(
                    value=None,
                    label="Prompt history",
                )

            with gr.Row():
                button = gr.Button("Send prompt")
                button.click(
                    self.send_prompt,
                    inputs=input,
                    outputs=[output, console, history],
                )
                input.submit(self.send_prompt, inputs=input, outputs=[output, console, history])


            with gr.Row():
                button = gr.Button("Clear patcher")
                button.click(self.clear_patcher, outputs=None)

            with gr.Row():
                button = gr.Button("Clear console")
                button.click(self.clear_console, outputs=console)

    def launch(self):
        self.demo.queue().launch(
            inbrowser=True,
            prevent_thread_lock=False,
        )

    def exit(self):
        self.client.close()
        self.demo.close()

@hydra.main(version_base=None, config_path=".", config_name="config")
def main(cfg: DictConfig):
    print(cfg)
    openai.api_key = cfg.api_key
    text_ui = TextUI(**cfg)
    text_ui.launch()


if __name__ == "__main__":
    main()
