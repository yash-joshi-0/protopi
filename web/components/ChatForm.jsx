const USERNAME_STORAGE_KEY = "protopi-chat-username";
const IMAGE_LONGEST_SIDE = 1600;
const IMAGE_SMALLEST_SIDE = 200;
const IMAGE_SHRINK_FACTOR = 0.75;
const IMAGE_QUALITY = 0.85;
const IMAGE_BACKDROP = "#0a0d0a";

// Contract: Read the remembered username, or an empty string when there is none.
function readRememberedUsername() {
  try {
    return window.localStorage.getItem(USERNAME_STORAGE_KEY) || "";
  } catch (error) {
    return "";
  }
}

// Contract: Remember the username for the next visit, ignoring a blocked store.
function rememberUsername(username) {
  try {
    window.localStorage.setItem(USERNAME_STORAGE_KEY, username);
  } catch (error) {
    return;
  }
}

// Contract: Decode a picked file into an image the canvas can draw.
function loadImage(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const image = new Image();

    image.onload = () => {
      URL.revokeObjectURL(url);
      resolve(image);
    };

    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("That file is not an image this browser can open."));
    };

    image.src = url;
  });
}

// Contract: Redraw the image no longer than the given side and encode it as JPEG.
function encodeImage(image, longestSide) {
  const naturalLongest = Math.max(image.naturalWidth, image.naturalHeight);
  const scale = Math.min(1, longestSide / naturalLongest);
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
  canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));

  const context = canvas.getContext("2d");
  context.fillStyle = IMAGE_BACKDROP;
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(image, 0, 0, canvas.width, canvas.height);

  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob) {
          resolve(blob);
        } else {
          reject(new Error("The image could not be prepared."));
        }
      },
      "image/jpeg",
      IMAGE_QUALITY,
    );
  });
}

// Contract: Read a blob as plain base64 text, without the data URL prefix.
function readBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
    reader.onerror = () => reject(new Error("The image could not be read."));
    reader.readAsDataURL(blob);
  });
}

// Contract: Shrink a picked image until it fits the server's limit, as base64.
async function prepareImage(file, maximumBytes) {
  const image = await loadImage(file);
  let longestSide = IMAGE_LONGEST_SIDE;
  let blob = await encodeImage(image, longestSide);

  while (blob.size > maximumBytes && longestSide > IMAGE_SMALLEST_SIDE) {
    longestSide = Math.round(longestSide * IMAGE_SHRINK_FACTOR);
    blob = await encodeImage(image, longestSide);
  }

  if (blob.size > maximumBytes) {
    throw new Error("That image is too large to send.");
  }

  return readBase64(blob);
}

// Component: ChatForm takes a username, a message, and an optional image and sends them.
function ChatForm(props) {
  const [username, setUsername] = React.useState(readRememberedUsername);
  const [body, setBody] = React.useState("");
  const [image, setImage] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const fileInputRef = React.useRef(null);

  // Contract: Forget the picked image and empty the file chooser.
  function clearImage() {
    setImage(null);

    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  }

  // Contract: Send the message, then hand the stored one back to the page.
  async function submit(event) {
    event.preventDefault();

    if (!username.trim()) {
      props.onError("A username is needed.");
      return;
    }

    if (!body.trim() && !image) {
      props.onError("Write a message or attach an image.");
      return;
    }

    setBusy(true);

    try {
      const request = { username: username.trim(), body: body.trim() };

      if (image) {
        try {
          request.image = await prepareImage(image, props.maximumImageBytes);
        } catch (error) {
          props.onError(error.message);
          return;
        }
      }

      const result = await sendJson("/api/messages", request);

      if (result.status !== 201) {
        props.onError(result.payload.error || "The message was not sent.");
        return;
      }

      rememberUsername(username.trim());
      setBody("");
      clearImage();
      props.onSent(result.payload.message);
    } catch (error) {
      props.onError("Chat unreachable: " + error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="chat-form" onSubmit={submit}>
      <label htmlFor="chat-username">Name</label>
      <input
        id="chat-username"
        maxLength={props.maximumUsernameLength}
        autoComplete="nickname"
        placeholder="who are you?"
        value={username}
        onChange={(event) => setUsername(event.target.value)}
      />

      <label htmlFor="chat-body">Message</label>
      <div className="chat-send">
        <input
          id="chat-body"
          maxLength={props.maximumMessageLength}
          autoComplete="off"
          placeholder="say something"
          value={body}
          onChange={(event) => setBody(event.target.value)}
        />

        <input
          id="chat-image"
          className="visually-hidden"
          type="file"
          accept="image/*"
          ref={fileInputRef}
          onChange={(event) => setImage(event.target.files[0] || null)}
        />
        <label htmlFor="chat-image" className="chat-attach">
          Image
        </label>

        <button type="submit" disabled={busy}>
          {busy ? "..." : "Send"}
        </button>
      </div>

      {image ? (
        <div className="chat-attachment">
          <span className="meta">{image.name}</span>
          <button type="button" onClick={clearImage} disabled={busy}>
            Remove
          </button>
        </div>
      ) : null}
    </form>
  );
}
